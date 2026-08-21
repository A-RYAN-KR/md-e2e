"""Test execution engine — dispatches IR steps to Playwright.

Orchestrates the full execution lifecycle:

* ``execute_step``   — runs one :class:`TestStep` against a ``Page``
* ``execute_scenario`` — runs a :class:`TestCase` (with setup/teardown
  hooks, data-matrix parameterisation, and failure screenshots)
* ``execute_suite``  — runs a :class:`TestSuite` (browser-per-suite,
  context-per-scenario, tracing on failure)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from playwright.async_api import Page, expect

from .browser import BrowserConfig, BrowserSession
from .custom_steps import StepNotImplementedError, _execute_custom_step
from .healing import HealingCache, heal_step, is_healable_step
from .locator import resolve_locator
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
    def status(self) -> StepStatus:
        if any(r.status == StepStatus.FAILED for r in self.scenario_results):
            return StepStatus.FAILED
        return StepStatus.PASSED



# StepNotImplementedError is imported from custom_steps for backwards compatibility


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

        await _dispatch_action(step, page, store, target, value)

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
                    await _dispatch_action(step, page, store, healed_id, value)
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
                                await _dispatch_action(step, page, store, healed_id_2, value)
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
            error=f"{type(exc).__name__}: {exc}",
        )



async def _dispatch_action(
    step: TestStep,
    page: Page,
    store: VariableStore,
    target: str | None,
    value: str | None,
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
            locator = resolve_locator(page, step.target_type, t_str)
            await locator.click()

        case ActionType.FILL:
            tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
            locator = resolve_locator(page, tt, t_str)
            await locator.fill(v_str)

        case ActionType.SELECT:
            # target_identifier = dropdown, value = option to select
            tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
            locator = resolve_locator(page, tt, t_str)
            await locator.select_option(label=v_str)

        case ActionType.HOVER:
            locator = resolve_locator(page, step.target_type, t_str)
            await locator.hover()

        case ActionType.PRESS:
            await page.keyboard.press(t_str)

        case ActionType.UPLOAD:
            # target = input element identifier, value = file path
            tt = TargetType.INPUT if step.target_type == TargetType.GENERIC else step.target_type
            locator = resolve_locator(page, tt, t_str)
            await locator.set_input_files(v_str)

        case ActionType.CHECK:
            tt = TargetType.CHECKBOX if step.target_type == TargetType.GENERIC else step.target_type
            locator = resolve_locator(page, tt, t_str)
            await locator.check()

        case ActionType.UNCHECK:
            tt = TargetType.CHECKBOX if step.target_type == TargetType.GENERIC else step.target_type
            locator = resolve_locator(page, tt, t_str)
            await locator.uncheck()

        # ── Assertions ───────────────────────────────────────────────
        case ActionType.ASSERT_VISIBLE:
            locator = resolve_locator(page, step.target_type, t_str)
            try:
                await expect(locator).to_be_visible()
            except Exception as e:
                # If first resolved element was hidden in DOM, check if any matching element is visible
                pattern = re.compile(re.escape(t_str), re.IGNORECASE)
                visible_fallback = page.locator("*:visible").filter(has_text=pattern).first
                try:
                    await expect(visible_fallback).to_be_visible()
                except Exception:
                    raise e

        case ActionType.ASSERT_HIDDEN:
            locator = resolve_locator(page, step.target_type, t_str)
            await expect(locator).to_be_hidden()

        case ActionType.ASSERT_URL:
            # target = comparison mode ("is", "contains", "matches")
            # value = expected URL/pattern
            await _assert_url(page, t_str, v_str)

        case ActionType.ASSERT_TITLE:
            # target = comparison mode, value = expected title
            await _assert_title(page, t_str, v_str)

        case ActionType.ASSERT_VALUE:
            # target = field name, value = "cmp:expected"
            await _assert_value(page, step, t_str, v_str)

        # ── State & Control ──────────────────────────────────────────
        case ActionType.WAIT:
            if v_str == "network_idle":
                await page.wait_for_load_state("networkidle")
            else:
                ms = int(value or "0") * 1000
                await page.wait_for_timeout(ms)

        case ActionType.STORE_VARIABLE:
            # target = element identifier, value = variable name
            locator = resolve_locator(page, step.target_type, t_str)
            tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
            if tag_name in ("input", "textarea", "select"):
                stored = await locator.input_value()
            else:
                stored = (await locator.text_content()) or ""
            store.store(v_str, stored.strip())

        case ActionType.CUSTOM:
            await _execute_custom_step(step, page, store)

        case _:
            raise StepNotImplementedError(step)


async def _assert_url(page: Page, cmp_mode: str, expected: str) -> None:
    """Assert page URL using the specified comparison mode."""
    match cmp_mode:
        case "is":
            await expect(page).to_have_url(expected)
        case "contains":
            await expect(page).to_have_url(re.compile(re.escape(expected)))
        case "matches":
            await expect(page).to_have_url(re.compile(expected))
        case _:
            await expect(page).to_have_url(expected)


async def _assert_title(page: Page, cmp_mode: str, expected: str) -> None:
    """Assert page title using the specified comparison mode."""
    match cmp_mode:
        case "is":
            await expect(page).to_have_title(expected)
        case "contains":
            await expect(page).to_have_title(re.compile(re.escape(expected)))
        case "matches":
            await expect(page).to_have_title(re.compile(expected))
        case _:
            await expect(page).to_have_title(expected)


async def _assert_value(
    page: Page,
    step: TestStep,
    field_name: str,
    raw_value: str,
) -> None:
    """Assert element value.  ``raw_value`` is ``"cmp:expected"``."""
    # Split on first colon to separate comparison mode from expected value
    if ":" in raw_value:
        cmp_mode, expected = raw_value.split(":", 1)
    else:
        cmp_mode, expected = "is", raw_value

    locator = resolve_locator(page, TargetType.INPUT, field_name)
    match cmp_mode:
        case "is":
            await expect(locator).to_have_value(expected)
        case "contains":
            await expect(locator).to_have_value(re.compile(re.escape(expected)))
        case "matches":
            await expect(locator).to_have_value(re.compile(expected))
        case _:
            await expect(locator).to_have_value(expected)


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
    import textwrap
    indented = textwrap.indent(code, "    ")
    wrapper = (
        "async def __hook__(page, store, browser, context, context_store, config):\n"
        f"{indented}\n"
    )
    
    local_scope: dict[str, Any] = {}
    exec(wrapper, globals(), local_scope)
    
    hook_fn = local_scope["__hook__"]
    await hook_fn(
        page,
        store,
        page.context.browser,
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
            run_name = f"{test_case.name} [row {row_idx + 1}: {param_summary}]"
        else:
            run_name = test_case.name

        # Merge parameters into a new store (non-mutating)
        run_store = store.merge(params)

        # Collect console logs
        console_logs: list[str] = []
        def log_handler(msg):
            console_logs.append(f"[{msg.type}] {msg.text}")
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
                                locator = resolve_locator(page, step.target_type, target)
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
                        continue
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
                except Exception:
                    pass  # Don't mask scenario errors

        # Resolve video path if recorded
        video_path = None
        if page.video:
            try:
                v_path = await page.video.path()
                if v_path:
                    video_path = Path(v_path)
            except Exception:
                pass

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
        # Run suite-level setup hook (before any scenario)
        # Note: No page yet, so setup code runs with a temporary page
        if suite.suite_setup_code:
            async with session.new_context() as (_ctx, setup_page):
                await _run_hook(suite.suite_setup_code, setup_page, store, cfg)

        for test_case in suite.test_cases:
            enable_trace = cfg.trace_dir is not None
            ctx_mgr = session.new_context(trace=enable_trace)
            async with ctx_mgr as (_ctx, page):
                scenario_results = await execute_scenario(
                    test_case,
                    page,
                    store,
                    cfg,
                    step_debug=step_debug,
                    suite_name=suite.name,
                    file_path=suite.file_path,
                    cache=cache,
                )

                # Save trace on failure & accumulate healing events
                for sr in scenario_results:
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
                except Exception:
                    pass

    suite_result.duration_ms = (time.perf_counter() - t0) * 1000
    return suite_result

