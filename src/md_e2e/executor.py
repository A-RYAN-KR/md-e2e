"""Test execution engine — dispatches IR steps to Playwright.

Orchestrates the full execution lifecycle:

* ``execute_step``   — runs one :class:`TestStep` against a ``Page``
* ``execute_scenario`` — runs a :class:`TestCase` (with setup/teardown
  hooks, data-matrix parameterisation, and failure screenshots)
* ``execute_suite``  — runs a :class:`TestSuite` (browser-per-suite,
  context-per-scenario, tracing on failure)
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import textwrap
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from enum import StrEnum
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page, expect

from .browser import BrowserConfig, BrowserSession
from .custom_steps import StepNotImplementedError, _execute_custom_step
from .healing import HealingCache, heal_step, is_healable_step
from .locator import resolve_locator, is_raw_selector, _css_escape_value
from .models import ActionType, HealingEvent, TargetType, TestCase, TestStep, TestSuite
from .variables import UndefinedVariableError, VariableStore

# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


class StepStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class StepResult:
    """Result of executing a single step."""

    step: TestStep
    status: StepStatus
    duration_ms: float = 0.0
    error: str | None = None
    screenshot_path: Path | None = None
    healed: bool = False
    healing_event: HealingEvent | None = None


@dataclass
class ScenarioResult:
    """Result of executing a single scenario (or one parameterised row)."""

    name: str
    status: StepStatus
    step_results: list[StepResult] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    trace_path: Path | None = None
    healing_events: list[HealingEvent] = field(default_factory=list)
    video_path: Path | None = None
    console_logs: list[str] = field(default_factory=list)


@dataclass
class SuiteResult:
    """Aggregated result of executing an entire suite."""

    name: str
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    duration_ms: float = 0.0
    healing_events: list[HealingEvent] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> int:
        return sum(1 for r in self.scenario_results if r.status == StepStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.scenario_results if r.status == StepStatus.FAILED)

    @property
    def total(self) -> int:
        return len(self.scenario_results)

    @property
    def total_scenarios(self) -> int:
        return len(self.scenario_results)

    @property
    def status(self) -> StepStatus:
        if self.error is not None:
            return StepStatus.FAILED
        if any(r.status == StepStatus.FAILED for r in self.scenario_results):
            return StepStatus.FAILED
        return StepStatus.PASSED



# StepNotImplementedError is imported from custom_steps for backwards compatibility



# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------

_NOISE_MARKERS = frozenset({
    "Call log:",
    "waiting for locator(",
    "============ logs ============",
    "Locator resolved to",
    "attempting click action",
    "attempting fill action",
})


def _format_error(
    exc: Exception,
    step: TestStep,
    file_path: Path | None = None,
) -> str:
    """Format a step execution error into a clean, readable message.

    Strips Playwright call logs and verbose internal traces, keeping
    the core error type, message, file location, and step text.
    """
    raw = f"{type(exc).__name__}: {exc}"
    lines = raw.split("\n")

    # Extract core error (first meaningful line)
    clean_lines: list[str] = []
    in_noise = False
    for line in lines:
        stripped = line.strip()
        if any(marker in stripped for marker in _NOISE_MARKERS):
            in_noise = True
            continue
        if in_noise and (stripped.startswith("- ") or stripped.startswith("→") or not stripped):
            if not stripped:
                in_noise = False
            continue
        in_noise = False
        clean_lines.append(line)

    core_msg = "\n".join(clean_lines).strip()

    # Build formatted error
    parts: list[str] = []
    if file_path:
        parts.append(f"File: {file_path}, Line {step.line_number}")
    else:
        parts.append(f"Line {step.line_number}")
    parts.append(f"Step: {step.raw_text}")
    parts.append(f"Error: {core_msg[:2000]}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


async def execute_step(
    step: TestStep,
    page: Page,
    store: VariableStore,
    suite_name: str = "",
    case_name: str = "",
    file_path: Path | None = None,
    config: BrowserConfig | None = None,
    cache: HealingCache | None = None,
) -> StepResult:
    """Execute a single :class:`TestStep` against a Playwright ``Page``.

    Variables in ``target_identifier`` and ``value`` are resolved via
    *store* before locator resolution and action dispatch.
    """
    t0 = time.perf_counter()

    try:
        # Resolve variables in identifiers
        target = (
            store.resolve(step.target_identifier, line_number=step.line_number)
            if step.target_identifier
            else None
        )
        value = (
            store.resolve(step.value, line_number=step.line_number)
            if step.value
            else None
        )

        await _dispatch_action(step, page, store, target, value, config)

        elapsed = (time.perf_counter() - t0) * 1000
        return StepResult(step=step, status=StepStatus.PASSED, duration_ms=elapsed)

    except Exception as exc:
        # Self-healing engine interceptor (skip for variable/syntax errors)
        if (
            not isinstance(exc, UndefinedVariableError)
            and config
            and config.enable_healing
            and is_healable_step(step)
        ):
            active_cache = cache or HealingCache(config.healing_cache_path or ".md_e2e_cache.json")
            cache_key = active_cache.make_key(suite_name, case_name, step.line_number, step.target_identifier or "", file_path=file_path)

            healed_id, event = await heal_step(
                page, step, suite_name, case_name, file_path, store, config, active_cache
            )

            if healed_id and event:
                try:
                    await _dispatch_action(step, page, store, healed_id, value, config)
                    elapsed = (time.perf_counter() - t0) * 1000
                    return StepResult(
                        step=step,
                        status=StepStatus.PASSED,
                        duration_ms=elapsed,
                        healed=True,
                        healing_event=event,
                    )
                except Exception:
                    # If execution with cached healed ID failed (stale cache), bust cache and re-heal!
                    if event.strategy_used == "cache":
                        active_cache.invalidate(cache_key)
                        healed_id_2, event_2 = await heal_step(
                            page, step, suite_name, case_name, file_path, store, config, active_cache
                        )
                        if healed_id_2 and event_2:
                            try:
                                await _dispatch_action(step, page, store, healed_id_2, value, config)
                                elapsed = (time.perf_counter() - t0) * 1000
                                return StepResult(
                                    step=step,
                                    status=StepStatus.PASSED,
                                    duration_ms=elapsed,
                                    healed=True,
                                    healing_event=event_2,
                                )
                            except Exception:
                                pass

        elapsed = (time.perf_counter() - t0) * 1000
        return StepResult(
            step=step,
            status=StepStatus.FAILED,
            duration_ms=elapsed,
            error=_format_error(exc, step, file_path),
        )



async def wait_and_pick_tier(tiers: list[Locator], timeout_ms: float) -> Locator:
    """Wait for at least one semantic tier to attach and return the winning tier locator (unconstrained).

    By joining the tiers with `.or_()` during the wait phase, we avoid serial timeouts.
    If multiple tiers attach simultaneously or a lower tier attaches while higher tiers are
    still mounting, semantic priority is resolved dynamically within the configured timeout budget.
    """
    if not tiers:
        raise ValueError("Locator tiers list cannot be empty")
    if len(tiers) == 1:
        return tiers[0]

    start_time = time.monotonic()

    union = tiers[0]
    for t in tiers[1:]:
        union = union.or_(t)

    try:
        await union.first.wait_for(state="attached", timeout=timeout_ms)
    except Exception:
        # If the union wait times out, return primary semantic locator (tier 0)
        # so that subsequent action throws standard Playwright TimeoutError
        return tiers[0]

    # Find highest priority attached tier
    highest_attached_idx = None
    for i, tier in enumerate(tiers):
        if await tier.count() > 0:
            highest_attached_idx = i
            break

    primary_count = getattr(tiers, "primary_count", 1)

    if highest_attached_idx == 0 or highest_attached_idx is None:
        return tiers[0]

    if highest_attached_idx < primary_count:
        # The attached tier is already a primary semantic tier (e.g. an exact input name/id or button)
        return tiers[highest_attached_idx]

    # The attached tier is a fallback tier (highest_attached_idx >= primary_count).
    # In dynamic SPAs, primary tiers (0 to primary_count - 1) might still be mounting.
    # Wait for primary tiers with the remaining timeout budget.
    higher_union = tiers[0]
    for t in tiers[1:primary_count]:
        higher_union = higher_union.or_(t)

    elapsed_ms = (time.monotonic() - start_time) * 1000.0
    remaining_ms = max(0.0, timeout_ms - elapsed_ms)

    if remaining_ms > 0:
        try:
            await higher_union.first.wait_for(state="attached", timeout=remaining_ms)
            for tier in tiers[:primary_count]:
                if await tier.count() > 0:
                    return tier
        except Exception:
            pass

    return tiers[highest_attached_idx]


async def wait_and_pick_locator(tiers: list[Locator], timeout_ms: float) -> Locator:
    """Wait for at least one semantic tier to attach, then return the highest priority match with .first applied.

    By joining the tiers with `.or_()` during the wait phase, we avoid serial timeouts.
    If multiple tiers attach simultaneously, iterating through the original `tiers` list
    ensures we always pick the one with the highest semantic priority, avoiding DOM-order priority inversion.
    """
    winning_tier = await wait_and_pick_tier(tiers, timeout_ms)
    return winning_tier.first


async def _dispatch_action(
    step: TestStep,
    page: Page,
    store: VariableStore,
    target: str | None,
    value: str | None,
    config: BrowserConfig | None = None,
) -> None:
    """Dispatch a step to the appropriate Playwright action."""
    t_str = target or ""
    v_str = value or ""

    match step.action_type:
        # ── Navigation ───────────────────────────────────────────────
        case ActionType.NAVIGATE:
            await page.goto(t_str, wait_until="domcontentloaded")

        case ActionType.RELOAD:
            await page.reload()

        # ── Interaction ──────────────────────────────────────────────
        case ActionType.CLICK:
            tiers = resolve_locator(page, step.target_type, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.click()

        case ActionType.FILL:
            tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
            tiers = resolve_locator(page, tt, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.fill(v_str)

        case ActionType.SELECT:
            # target_identifier = dropdown, value = option to select
            css_t_str = _css_escape_value(t_str)
            pattern_sel = re.compile(r"^\s*" + re.escape(t_str) + r"\s*$", re.IGNORECASE)
            contains_sel = re.compile(re.escape(t_str), re.IGNORECASE)

            # Build candidate tiers constrained to <select> elements to avoid matching text inputs
            if step.target_type == TargetType.TESTID:
                select_tiers = [
                    page.get_by_test_id(t_str).locator("xpath=self::select | .//select"),
                    page.get_by_test_id(t_str),
                ]
            elif is_raw_selector(t_str):
                select_tiers = [page.locator(t_str)]
            else:
                from .locator import TierList
                select_tiers = TierList([
                    page.get_by_label(pattern_sel).locator("xpath=self::select | .//select").or_(page.get_by_label(pattern_sel)),
                    page.locator(
                        f'select[name="{css_t_str}" i], select[id="{css_t_str}" i], '
                        f'select[aria-label*="{css_t_str}" i], select[data-testid*="{css_t_str}" i]'
                    ),
                    page.get_by_label(contains_sel).locator("xpath=self::select | .//select").or_(page.get_by_label(contains_sel)),
                    # Proximity fallback: <label>X</label> + <select> or container
                    page.locator(
                        f'label:has-text("{css_t_str}") + select, label:has-text("{css_t_str}") ~ select'
                    ),
                    page.locator(
                        ':is(.form-group, .form-control, .field, div, p)'
                        f':has(> label:has-text("{css_t_str}"))'
                    ).locator("select"),
                ], primary_count=2)

            start_time = time.monotonic()
            total_timeout = float(config.timeout if config else 30_000)
            deadline = start_time + (total_timeout / 1000.0)

            def remaining_ms() -> float:
                return max(0.0, (deadline - time.monotonic()) * 1000.0)

            # Subdivide total timeout so locating select cannot starve option selection
            select_timeout = max(500.0, total_timeout * 0.4) if total_timeout >= 1000.0 else total_timeout
            select_elem = await wait_and_pick_locator(select_tiers, select_timeout)

            # Ensure we target the actual <select> element if a wrapper matched
            select_child = select_elem.locator("xpath=self::select | .//select")
            target = select_child.first if await select_child.count() > 0 else select_elem

            # Allocate remaining timeout budget across label attempt and value fallback
            budget = remaining_ms()
            if budget <= 0:
                # If resolution consumed the entire budget, attempt immediate select to let Playwright throw standard error
                await target.select_option(label=v_str, timeout=1.0)
            else:
                label_timeout = max(100.0, budget * 0.6) if budget >= 200.0 else budget
                try:
                    await target.select_option(label=v_str, timeout=label_timeout)
                except Exception as label_err:
                    val_budget = remaining_ms()
                    if val_budget <= 0:
                        raise label_err
                    await target.select_option(value=v_str, timeout=val_budget)

        case ActionType.HOVER:
            tiers = resolve_locator(page, step.target_type, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.hover()

        case ActionType.PRESS:
            await page.keyboard.press(t_str)

        case ActionType.UPLOAD:
            # target = input element identifier, value = file path
            tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
            tiers = resolve_locator(page, tt, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.set_input_files(v_str)

        case ActionType.CHECK:
            tt = TargetType.CHECKBOX if step.target_type == TargetType.GENERIC else step.target_type
            tiers = resolve_locator(page, tt, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.check()

        case ActionType.UNCHECK:
            tt = TargetType.CHECKBOX if step.target_type == TargetType.GENERIC else step.target_type
            tiers = resolve_locator(page, tt, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            await locator.uncheck()

        # ── Assertions ───────────────────────────────────────────────
        case ActionType.ASSERT_VISIBLE:
            tiers = resolve_locator(page, step.target_type, t_str)
            locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
            # Split configured timeout into 80% primary, 20% fallback to prevent 2x timeout delay
            timeout_ms = config.timeout if config else 30_000
            try:
                await expect(locator).to_be_visible(timeout=timeout_ms * 0.8)
            except Exception as e:
                if step.target_type not in (TargetType.GENERIC, TargetType.TEXT):
                    raise e
                pattern = re.compile(r"^\s*" + re.escape(t_str) + r"\s*$", re.IGNORECASE)
                # Target specific text containers with :visible filtering rather than matching hidden duplicates
                visible_fallback = page.locator(":is(button, a, p, span, h1, h2, h3, h4, h5, h6, label, td, li):visible") \
                    .filter(has_text=pattern).first
                try:
                    await expect(visible_fallback).to_be_visible(timeout=timeout_ms * 0.2)
                except Exception:
                    raise e

        case ActionType.ASSERT_HIDDEN:
            tiers = resolve_locator(page, step.target_type, t_str)
            timeout_ms = config.timeout if config else 30_000
            # For hidden assertions, verify ALL matching elements across all tiers are hidden.
            # If no elements exist across any tier, it passes (absent element is hidden).
            # If any element in any tier is visible, it must fail.
            found_any = False
            for tier in tiers:
                count = await tier.count()
                if count > 0:
                    found_any = True
                    for i in range(count):
                        await expect(tier.nth(i)).to_be_hidden(timeout=timeout_ms)
            if not found_any:
                # No matching elements found anywhere in DOM — effectively hidden, PASS.
                pass

        case ActionType.ASSERT_URL:
            # target = comparison mode ("is", "contains", "matches")
            # value = expected URL/pattern
            await _assert_url(page, t_str, v_str, config)

        case ActionType.ASSERT_TITLE:
            # target = comparison mode, value = expected title
            await _assert_title(page, t_str, v_str, config)

        case ActionType.ASSERT_VALUE:
            # target = field name, value = "cmp:expected"
            await _assert_value(page, step, t_str, v_str, config)

        case ActionType.ASSERT_VARIABLE:
            # target = variable name, value = "cmp:expected"
            _assert_variable_value(store, t_str, v_str)

        # ── State & Control ──────────────────────────────────────────
        case ActionType.WAIT:
            if v_str == "network_idle":
                await page.wait_for_load_state("networkidle")
            else:
                ms = int(value or "0") * 1000
                await page.wait_for_timeout(ms)

        case ActionType.WAIT_URL:
            # target = comparison mode ("contains", "is", "matches")
            # value = expected URL/pattern
            if t_str in ("contains",):
                await page.wait_for_url(re.compile(re.escape(v_str)))
            elif t_str in ("matches",):
                await page.wait_for_url(re.compile(v_str))
            else:
                # Use exact regex match instead of glob matching
                await page.wait_for_url(re.compile(r"^" + re.escape(v_str) + r"$"))

        case ActionType.STORE_VARIABLE:
            # target = element identifier, value = variable name
            tiers = resolve_locator(page, step.target_type, t_str)
            winning_tier = await wait_and_pick_tier(tiers, config.timeout if config else 30_000)
            # When multiple elements match in the winning tier, prefer the visible instance to avoid extracting
            # stale/hidden duplicates (e.g. inactive mobile nav), while preserving the ability
            # to extract from genuinely hidden elements when only a hidden element exists.
            target = None
            count = await winning_tier.count()
            if count > 1:
                for i in range(count):
                    candidate = winning_tier.nth(i)
                    if await candidate.is_visible():
                        target = candidate
                        break
            if target is None:
                target = winning_tier.first

            tag_name = await target.evaluate("el => el.tagName.toLowerCase()")
            if tag_name in ("input", "textarea", "select"):
                stored = await target.input_value()
            else:
                stored = (await target.text_content()) or ""
            store.store(v_str, stored.strip())

        case ActionType.CUSTOM:
            await _execute_custom_step(step, page, store)

        case ActionType.ASSERT_COUNT:
            raise NotImplementedError(
                f"ASSERT_COUNT is reserved but not yet implemented. "
                f"Step: {step.raw_text} at line {step.line_number}"
            )

        case _:
            raise StepNotImplementedError(step)


def _assert_variable_value(
    store: VariableStore,
    var_name: str,
    raw_value: str,
) -> None:
    """Assert stored variable value against expected value."""
    if ":" in raw_value:
        cmp_mode, expected = raw_value.split(":", 1)
    else:
        cmp_mode, expected = "is", raw_value

    actual = store.get(var_name)
    cmp_lower = cmp_mode.lower()
    if cmp_lower in ("is", "equals", "equal", "=="):
        assert actual == expected, f"Expected variable '{var_name}' to equal '{expected}', but got '{actual}'"
    elif cmp_lower in ("contains", "contain"):
        assert expected in actual, f"Expected variable '{var_name}' ('{actual}') to contain '{expected}'"
    elif cmp_lower in ("matches", "match"):
        assert re.search(expected, actual), f"Expected variable '{var_name}' ('{actual}') to match regex '{expected}'"
    else:
        assert actual == expected, f"Expected variable '{var_name}' to equal '{expected}', but got '{actual}'"


async def _assert_url(page: Page, cmp_mode: str, expected: str, config: BrowserConfig | None = None) -> None:
    """Assert page URL using the specified comparison mode."""
    timeout_ms = config.timeout if config else 30_000
    match cmp_mode:
        case "is":
            await expect(page).to_have_url(expected, timeout=timeout_ms)
        case "contains":
            await expect(page).to_have_url(re.compile(re.escape(expected)), timeout=timeout_ms)
        case "matches":
            await expect(page).to_have_url(re.compile(expected), timeout=timeout_ms)
        case _:
            await expect(page).to_have_url(expected, timeout=timeout_ms)


async def _assert_title(page: Page, cmp_mode: str, expected: str, config: BrowserConfig | None = None) -> None:
    """Assert page title using the specified comparison mode."""
    timeout_ms = config.timeout if config else 30_000
    match cmp_mode:
        case "is":
            await expect(page).to_have_title(expected, timeout=timeout_ms)
        case "contains":
            await expect(page).to_have_title(re.compile(re.escape(expected)), timeout=timeout_ms)
        case "matches":
            await expect(page).to_have_title(re.compile(expected), timeout=timeout_ms)
        case _:
            await expect(page).to_have_title(expected, timeout=timeout_ms)


async def _assert_value(
    page: Page,
    step: TestStep,
    field_name: str,
    raw_value: str,
    config: BrowserConfig | None = None,
) -> None:
    """Assert element value.  ``raw_value`` is ``"cmp:expected"``."""
    # Split on first colon to separate comparison mode from expected value
    if ":" in raw_value:
        cmp_mode, expected = raw_value.split(":", 1)
    else:
        cmp_mode, expected = "is", raw_value

    timeout_ms = config.timeout if config else 30_000
    tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
    tiers = resolve_locator(page, tt, field_name)
    locator = await wait_and_pick_locator(tiers, timeout_ms)
    match cmp_mode:
        case "is":
            await expect(locator).to_have_value(expected, timeout=timeout_ms)
        case "contains":
            await expect(locator).to_have_value(re.compile(re.escape(expected)), timeout=timeout_ms)
        case "matches":
            await expect(locator).to_have_value(re.compile(expected), timeout=timeout_ms)
        case _:
            await expect(locator).to_have_value(expected, timeout=timeout_ms)


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------


async def _capture_screenshot(
    page: Page,
    config: BrowserConfig,
    name: str,
) -> Path | None:
    """Capture a screenshot if configured. Returns path or None."""
    if not config.screenshot_dir:
        return None
    try:
        ss_dir = Path(config.screenshot_dir)
        ss_dir.mkdir(parents=True, exist_ok=True)
        # Sanitise name for filesystem
        safe_name = re.sub(r'[^\w\-.]', '_', name)
        path = ss_dir / f"{safe_name}.png"
        await page.screenshot(path=str(path), full_page=True)
        return path
    except Exception:
        return None


async def _run_hook(
    code: str,
    page: Page,
    store: VariableStore,
    config: BrowserConfig,
) -> None:
    """Execute embedded Python setup/teardown code.

    The code runs with a scoped namespace containing ``page``, ``context``,
    ``store``, ``config``, ``browser``, and ``context_store``.
    """
    indented = textwrap.indent(code, "    ")
    wrapper = (
        "async def __hook__(page, store, browser, context, context_store, config):\n"
        f"{indented}\n"
    )
    # Execute in a fully trusted Python environment with standard globals.
    # Python setup/teardown hooks execute as fully trusted code with the
    # same privileges as the test runner.
    exec_globals: dict[str, Any] = {
        "__builtins__": __builtins__,
        "asyncio": __import__("asyncio"),
        "re": __import__("re"),
        "json": __import__("json"),
    }
    local_scope: dict[str, Any] = {}
    exec(wrapper, exec_globals, local_scope)
    
    hook_fn = local_scope["__hook__"]
    browser_instance = getattr(page.context, "browser", None)
    await hook_fn(
        page,
        store,
        browser_instance,
        page.context,
        store,
        config
    )


async def execute_scenario(
    test_case: TestCase,
    page: Page,
    store: VariableStore,
    config: BrowserConfig,
    step_debug: bool = False,
    suite_name: str = "",
    file_path: Path | None = None,
    cache: HealingCache | None = None,
    base_row_idx: int = 0,
) -> list[ScenarioResult]:
    """Execute a :class:`TestCase` scenario.

    If the scenario has a data-matrix (``parameters``), each row is
    executed as a distinct run, producing a ``list[ScenarioResult]``
    with names like ``"Login [row 1: user=admin]"``.

    If there are no parameters, returns a single-element list.
    """
    parameter_sets = test_case.parameters if test_case.parameters else [{}]
    results: list[ScenarioResult] = []
    active_cache = cache or HealingCache(config.healing_cache_path or ".md_e2e_cache.json")

    for row_idx, params in enumerate(parameter_sets):
        # Build row-specific name
        if test_case.parameters:
            param_summary = ", ".join(f"{k}={v}" for k, v in params.items())
            run_name = f"{test_case.name} [row {row_idx + 1 + base_row_idx}: {param_summary}]"
        else:
            run_name = test_case.name

        # Merge parameters into a new store (non-mutating)
        run_store = store.merge(params)

        # Collect console logs
        console_logs: list[str] = []
        def _make_log_handler(log_list):
            def handler(msg):
                log_list.append(f"[{msg.type}] {msg.text}")
            return handler
        log_handler = _make_log_handler(console_logs)
        page.on("console", log_handler)

        t0 = time.perf_counter()
        step_results: list[StepResult] = []
        scenario_error: str | None = None
        scenario_status = StepStatus.PASSED
        scenario_healing_events: list[HealingEvent] = []

        try:
            # Run setup hook
            if test_case.setup_code:
                await _run_hook(test_case.setup_code, page, run_store, config)

            # Execute steps
            step_idx = 0
            while step_idx < len(test_case.steps):
                step = test_case.steps[step_idx]
                advance_after = True

                if step_debug:
                    # 1. Highlight target element if applicable
                    if step.action_type in (
                        ActionType.CLICK,
                        ActionType.FILL,
                        ActionType.SELECT,
                        ActionType.HOVER,
                        ActionType.CHECK,
                        ActionType.UNCHECK,
                        ActionType.ASSERT_VISIBLE,
                        ActionType.ASSERT_VALUE,
                    ):
                        try:
                            target = run_store.resolve(step.target_identifier, line_number=step.line_number) if step.target_identifier else None
                            if target:
                                tiers = resolve_locator(page, step.target_type, target)
                                locator = await wait_and_pick_locator(tiers, config.timeout if config else 30_000)
                                await locator.highlight()
                        except Exception:
                            pass  # Proceed to prompt even if highlighting fails

                    # 2. Print step info with Rich
                    from rich import print as rprint
                    rprint(f"\n[bold yellow]Debug Step (line {step.line_number}):[/bold yellow] {step.raw_text}")
                    
                    # 3. Prompt user asynchronously using a worker thread to keep the loop responsive
                    import asyncio
                    action = None
                    while not action:
                        prompt_msg = "Debugger [[Enter] next | [r] retry | [e] edit step | [s] skip | [q] quit]: "
                        choice = (await asyncio.to_thread(input, prompt_msg)).strip().lower()
                        if choice == "":
                            action = "next"
                        elif choice == "r":
                            action = "retry"
                        elif choice == "e":
                            action = "edit"
                        elif choice == "s":
                            action = "skip"
                        elif choice == "q":
                            action = "quit"

                    # 4. Handle debugger action
                    if action == "quit":
                        raise KeyboardInterrupt("Debugger terminated by user")
                    elif action == "retry":
                        advance_after = False
                    elif action == "skip":
                        rprint("[yellow]Skipped step[/yellow]")
                        step_results.append(StepResult(step=step, status=StepStatus.SKIPPED))
                        step_idx += 1
                        continue
                    elif action == "edit":
                        new_raw = (await asyncio.to_thread(input, f"Edit step (current: {step.raw_text}): ")).strip()
                        from .dsl_parser import parse_step
                        new_step, error = parse_step(new_raw, line_number=step.line_number)
                        test_case.steps[step_idx] = new_step
                        if error:
                            rprint(f"[red]Warning: parse warning: {error.message}[/red]")
                        continue

                result = await execute_step(
                    step,
                    page,
                    run_store,
                    suite_name=suite_name,
                    case_name=test_case.name,
                    file_path=file_path,
                    config=config,
                    cache=active_cache,
                )
                step_results.append(result)
                if result.healed and result.healing_event:
                    scenario_healing_events.append(result.healing_event)

                if result.status == StepStatus.FAILED:
                    scenario_status = StepStatus.FAILED
                    scenario_error = result.error

                    # Screenshot on failure
                    ss_path = await _capture_screenshot(
                        page, config,
                        f"{run_name}_step{step.line_number}",
                    )
                    result.screenshot_path = ss_path

                    # Stop scenario on first failure
                    break

                if advance_after:
                    step_idx += 1

        except Exception as exc:
            scenario_status = StepStatus.FAILED
            scenario_error = f"{type(exc).__name__}: {exc}"

        finally:
            # Detach console listener
            try:
                page.remove_listener("console", log_handler)
            except Exception:
                pass

            # Run teardown hook (always, even on failure)
            if test_case.teardown_code:
                try:
                    await _run_hook(test_case.teardown_code, page, run_store, config)
                except Exception as e:
                    logger.error(f"Error in teardown hook for '{run_name}': {e}")
                    if scenario_status == StepStatus.PASSED:
                        scenario_status = StepStatus.FAILED
                        scenario_error = f"Teardown error: {e}"

        # Commit scenario-local stored variables back to parent store if not clean_session and not matrix
        is_matrix = bool(test_case.parameters) or bool(params)
        if not config.clean_session and not is_matrix:
            run_store.commit_to(store)

        # Video path will be resolved after context closes
        video_path = None

        elapsed = (time.perf_counter() - t0) * 1000
        results.append(ScenarioResult(
            name=run_name,
            status=scenario_status,
            step_results=step_results,
            duration_ms=elapsed,
            error=scenario_error,
            healing_events=scenario_healing_events,
            video_path=video_path,
            console_logs=console_logs,
        ))

    return results


# ---------------------------------------------------------------------------
# Suite execution
# ---------------------------------------------------------------------------


async def execute_suite(
    suite: TestSuite,
    config: BrowserConfig | None = None,
    step_debug: bool = False,
) -> SuiteResult:
    """Execute an entire :class:`TestSuite`.

    Launches **one browser** for the suite, then creates a fresh
    **BrowserContext + Page per scenario** for full isolation.

    Enables tracing per-scenario when ``config.trace_dir`` is set;
    traces are saved on failure.
    """
    cfg = config or BrowserConfig()
    store = VariableStore()
    cache = HealingCache(cfg.healing_cache_path or ".md_e2e_cache.json")

    suite_result = SuiteResult(name=suite.name)
    t0 = time.perf_counter()

    async with BrowserSession(cfg) as session:
        temp_state_file = None
        # Run suite-level setup hook and preserve session state if cookies/storage changed
        # Note: No page yet, so setup code runs with a temporary page
        if suite.suite_setup_code:
            async with session.new_context() as (setup_ctx, setup_page):
                await _run_hook(suite.suite_setup_code, setup_page, store, cfg)
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
                    temp_state_file = tf.name
                await setup_ctx.storage_state(path=temp_state_file)
                cfg.storage_state = temp_state_file

        try:
            for test_case in suite.test_cases:
                parameter_sets = test_case.parameters if test_case.parameters else [{}]
                
                for row_idx, params in enumerate(parameter_sets):
                    # Create per-scenario variable store when clean_session is enabled.
                    # Use merge({}) to preserve suite-level variables while getting
                    # fresh generated values (RANDOM_*, TIMESTAMP).
                    scenario_store = store.merge({}) if cfg.clean_session else store

                    enable_trace = cfg.trace_dir is not None
                    ctx_mgr = session.new_context(trace=enable_trace)
                    async with ctx_mgr as (_ctx, page):
                        import copy
                        tc = copy.copy(test_case)
                        tc.steps = [copy.deepcopy(s) for s in test_case.steps]
                        if test_case.parameters:
                            tc.parameters = [params]
                        else:
                            tc.parameters = []

                        scenario_results = await execute_scenario(
                            tc,
                            page,
                            scenario_store,
                            cfg,
                            step_debug=step_debug,
                            suite_name=suite.name,
                            file_path=suite.file_path,
                            cache=cache,
                            base_row_idx=row_idx,
                        )

                        video_ref = page.video

                        # Save trace on failure & accumulate healing events, get video
                        for sr in scenario_results:
                            if video_ref:
                                try:
                                    v_path = await video_ref.path()
                                    if v_path:
                                        sr.video_path = Path(v_path)
                                except Exception as e:
                                    logger.warning(f"Failed to retrieve video path: {e}")

                            if sr.healing_events:
                                suite_result.healing_events.extend(sr.healing_events)
                            if sr.status == StepStatus.FAILED and enable_trace:
                                safe = re.sub(r'[^\w\-.]', '_', sr.name)
                                trace_path = await ctx_mgr.save_trace(safe)
                                sr.trace_path = trace_path

                        suite_result.scenario_results.extend(scenario_results)

            # Run suite-level teardown hook
            if suite.suite_teardown_code:
                async with session.new_context() as (_ctx, teardown_page):
                    try:
                        await _run_hook(
                            suite.suite_teardown_code, teardown_page, store, cfg,
                        )
                    except Exception as e:
                        logger.error(f"Error in suite-level teardown hook: {e}")
                        suite_result.error = f"Suite teardown error: {e}"
        finally:
            if temp_state_file and os.path.exists(temp_state_file):
                os.remove(temp_state_file)

    suite_result.duration_ms = (time.perf_counter() - t0) * 1000
    return suite_result

