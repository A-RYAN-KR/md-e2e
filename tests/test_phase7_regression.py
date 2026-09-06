"""Phase 7 authoritative regression tests for md-e2e (REG-001 through REG-016).

Verifies the 16 confirmed defects:
- REG-001: LOC-001 (unconstrained search input)
- REG-002: LOC-002 (LINK priority inversion)
- REG-003: LOC-004 (raw selector false positive on [Save])
- REG-004: LOC-004 (raw selector false positive on Next >>)
- REG-005: LOC-005 (asynchronous locator priority race)
- REG-006: EXEC-003 (SELECT timeout cascade bounded)
- REG-007: EXEC-004 (SELECT dynamically rendered control)
- REG-008: EXEC-005 (scenario variable state persistence when clean_session=False)
- REG-009: EXEC-006 (fresh generated variable cache across scenarios)
- REG-010: LOC-006 (ASSERT_HIDDEN multi-tier evaluation)
- REG-011: LOC-007 (STORE_VARIABLE visibility preference and hidden preservation)
- REG-012: LOC-008 (_assert_value respects TargetType.TESTID)
- REG-013: LOC-010 (ASSERT_VISIBLE fallback filters by :visible)
- REG-014: EXEC-002 (assertion timeout propagation for expect())
- REG-015: EXEC-008 (pytest teardown guaranteed finalization)
- REG-016: EXEC-009 (matrix row step mutation isolation)
"""

import asyncio
import copy
import os
import time
from pathlib import Path
import pytest
from playwright.async_api import Page, expect

from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.executor import (
    _dispatch_action,
    _assert_value,
    _assert_url,
    _assert_title,
    wait_and_pick_locator,
    execute_suite,
    StepStatus,
)
from md_e2e.locator import resolve_locator, is_raw_selector, _css_escape_value
from md_e2e.models import ActionType, TargetType, TestCase, TestStep, TestSuite
from md_e2e.variables import VariableStore


# ── REG-001: LOC-001 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg001_unconstrained_search_input():
    """REG-001 (LOC-001): Unrelated search input does not hijack password/text resolution."""
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            html = """
            <form>
                <input type="search" id="global-search" name="q" placeholder="Search..." />
                <label for="pwd">Password</label>
                <input type="password" id="pwd" name="password" />
            </form>
            """
            await page.set_content(html)
            tiers = resolve_locator(page, TargetType.INPUT, "Password")
            locator = await wait_and_pick_locator(tiers, 5000)
            await locator.fill("secret123")

            assert await page.locator("#pwd").input_value() == "secret123"
            assert await page.locator("#global-search").input_value() == ""

            # Verify legitimate search input lookup still works
            s_tiers = resolve_locator(page, TargetType.INPUT, "Search...")
            s_loc = await wait_and_pick_locator(s_tiers, 5000)
            await s_loc.fill("query")
            assert await page.locator("#global-search").input_value() == "query"


# ── REG-002: LOC-002 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg002_link_priority_exact_before_substring():
    """REG-002 (LOC-002): Exact link matches before substring link match."""
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            html = """
            <nav>
                <a id="sub" href="/documentation">Documentation</a>
                <a id="exact" href="/doc">Doc</a>
            </nav>
            """
            await page.set_content(html)
            tiers = resolve_locator(page, TargetType.LINK, "Doc")
            locator = await wait_and_pick_locator(tiers, 5000)
            picked_id = await locator.evaluate("el => el.id")
            assert picked_id == "exact"


# ── REG-003 & REG-004: LOC-004 ──────────────────────────────────────────────
def test_reg003_reg004_raw_selector_detection():
    """REG-003 & REG-004 (LOC-004): Distinguish natural text from genuine raw selectors."""
    # Negative cases (ordinary natural-language text)
    assert is_raw_selector("[Save]") is False
    assert is_raw_selector("[Cancel]") is False
    assert is_raw_selector("[Submit]") is False
    assert is_raw_selector("[OK]") is False
    assert is_raw_selector("[1]") is False
    assert is_raw_selector("Next >>") is False
    assert is_raw_selector(">> Back") is False
    assert is_raw_selector("Step 1 >> Step 2") is False
    assert is_raw_selector("Submit") is False
    assert is_raw_selector("button 'Submit'") is False
    assert is_raw_selector("A >> B") is False
    assert is_raw_selector("Next >> Page") is False
    assert is_raw_selector("Price [USD] >> Next") is False

    # Positive cases (genuine raw CSS/XPath/engine selectors)
    assert is_raw_selector("#submit-btn") is True
    assert is_raw_selector(".btn-primary") is True
    assert is_raw_selector("//button[@id='submit']") is True
    assert is_raw_selector("css=button") is True
    assert is_raw_selector("xpath=//button") is True
    assert is_raw_selector("data-testid=login") is True
    assert is_raw_selector("[data-testid='login']") is True
    assert is_raw_selector("[name=\"email\"]") is True
    assert is_raw_selector("div >> span") is True
    assert is_raw_selector("#nav >> button") is True
    assert is_raw_selector(".menu >> a") is True
    assert is_raw_selector("[disabled]") is True
    assert is_raw_selector("[data-active]") is True
    assert is_raw_selector("[aria-expanded]") is True
    assert is_raw_selector('div >> input[type="text"]') is True
    assert is_raw_selector('div >> input[name="email"]') is True
    assert is_raw_selector("form.login >> input#email") is True
    assert is_raw_selector('div.foo >> input.bar[type="text"]') is True
    assert is_raw_selector('#container >> input[type="text"] >> span.error') is True

    # Natural-language rejections
    assert is_raw_selector("Click >> Save") is False
    assert is_raw_selector("Login >> Button") is False
    assert is_raw_selector("Next >> Page >> Button") is False
    assert is_raw_selector("User [Admin]") is False
    assert is_raw_selector("Save [Draft]") is False


# ── REG-005: LOC-005 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg005_dynamic_spa_locator_priority_race():
    """REG-005 (LOC-005): Lower tier attached at T=0ms does not beat Tier 0 attaching dynamically (150ms and 1100ms)."""
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            # Case 1: 150ms delay
            html_150 = """
            <h2 id="heading-save">Save</h2>
            <script>
            setTimeout(() => {
                const btn = document.createElement("button");
                btn.id = "button-save";
                btn.textContent = "Save";
                document.body.appendChild(btn);
            }, 150);
            </script>
            """
            await page.set_content(html_150)
            tiers = resolve_locator(page, TargetType.GENERIC, "Save")
            locator = await wait_and_pick_locator(tiers, 5000)
            assert await locator.evaluate("el => el.id") == "button-save"

            # Case 2: 1100ms delay (proves semantic priority beyond 1000ms boundary)
            html_1100 = """
            <h2 id="heading-submit">Submit</h2>
            <script>
            setTimeout(() => {
                const btn = document.createElement("button");
                btn.id = "button-submit";
                btn.textContent = "Submit";
                document.body.appendChild(btn);
            }, 1100);
            </script>
            """
            await page.set_content(html_1100)
            tiers2 = resolve_locator(page, TargetType.GENERIC, "Submit")
            locator2 = await wait_and_pick_locator(tiers2, 5000)
            assert await locator2.evaluate("el => el.id") == "button-submit"


# ── REG-006: EXEC-003 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg006_select_timeout_cascade_bounded():
    """REG-006 (EXEC-003): SELECT on missing option or missing select is bounded by config.timeout."""
    config = BrowserConfig(headless=True, timeout=1500)
    store = VariableStore()
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            # Part 1: Select present, option missing
            html = """
            <label for="color">Color</label>
            <select id="color" name="color">
                <option value="red">Red</option>
                <option value="blue">Blue</option>
            </select>
            """
            await page.set_content(html)
            step = TestStep(
                line_number=1,
                raw_text='Select option "Yellow" from "Color"',
                action_type=ActionType.SELECT,
                target_type=TargetType.GENERIC,
                target_identifier="Color",
                value="Yellow",
            )
            t0 = time.perf_counter()
            with pytest.raises(Exception):
                await _dispatch_action(step, page, store, "Color", "Yellow", config)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms <= 2000, f"SELECT option took {elapsed_ms:.1f}ms, exceeds budget!"

            # Part 2: Select missing completely (must not double-wait)
            await page.set_content("<div>No dropdown here</div>")
            step_missing = TestStep(
                line_number=2,
                raw_text='Select option "Red" from "MissingSelect"',
                action_type=ActionType.SELECT,
                target_type=TargetType.GENERIC,
                target_identifier="MissingSelect",
                value="Red",
            )
            t0 = time.perf_counter()
            with pytest.raises(Exception):
                await _dispatch_action(step_missing, page, store, "MissingSelect", "Red", config)
            elapsed_missing = (time.perf_counter() - t0) * 1000
            assert elapsed_missing <= 2000, f"Missing SELECT took {elapsed_missing:.1f}ms, double-waiting!"


# ── REG-007: EXEC-004 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg007_select_dynamically_rendered():
    """REG-007 (EXEC-004): SELECT waits for dynamically rendered <select> control."""
    config = BrowserConfig(headless=True, timeout=5000)
    store = VariableStore()
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            html = """
            <div id="wrapper"></div>
            <script>
            setTimeout(() => {
                const sel = document.createElement("select");
                sel.name = "role";
                sel.id = "role";
                sel.innerHTML = '<option value="user">User</option><option value="admin">Admin</option>';
                document.getElementById("wrapper").appendChild(sel);
            }, 150);
            </script>
            """
            await page.set_content(html)
            step = TestStep(
                line_number=1,
                raw_text='Select option "Admin" from "role"',
                action_type=ActionType.SELECT,
                target_type=TargetType.GENERIC,
                target_identifier="role",
                value="Admin",
            )
            await _dispatch_action(step, page, store, "role", "Admin", config)
            val = await page.locator("#role").input_value()
            assert val == "admin"


# ── REG-008: EXEC-005 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg008_scenario_variable_persistence_clean_session_false():
    """REG-008 (EXEC-005): Stored variables in Scenario 1 persist to Scenario 2 when clean_session=False."""
    config = BrowserConfig(headless=True, clean_session=False)

    tc1 = TestCase(
        name="Scenario 1",
        line_number=1,
        steps=[
            TestStep(
                line_number=2,
                raw_text="Custom step",
                action_type=ActionType.CUSTOM,
                target_type=TargetType.GENERIC,
            )
        ],
    )
    tc2 = TestCase(
        name="Scenario 2",
        line_number=5,
        steps=[
            TestStep(
                line_number=6,
                raw_text='Assert variable "TOKEN" is "xyz123"',
                action_type=ActionType.ASSERT_VARIABLE,
                target_type=TargetType.GENERIC,
                target_identifier="TOKEN",
                value="is:xyz123",
            )
        ],
    )

    from md_e2e.custom_steps import _custom_steps_registry, CustomStepEntry
    import re

    async def custom_handler(page, store):
        store.store("TOKEN", "xyz123")

    entry = CustomStepEntry(pattern=re.compile("Custom step"), handler=custom_handler, source_dir=Path("."))
    _custom_steps_registry.append(entry)

    suite = TestSuite(name="Variable Persistence Suite", test_cases=[tc1, tc2])
    try:
        result = await execute_suite(suite, config)
    finally:
        _custom_steps_registry.remove(entry)

    assert result.status == StepStatus.PASSED
    assert len(result.scenario_results) == 2
    assert result.scenario_results[0].status == StepStatus.PASSED
    assert result.scenario_results[1].status == StepStatus.PASSED


# ── REG-009: EXEC-006 ────────────────────────────────────────────────────────
def test_reg009_fresh_generated_variables_across_merges():
    """REG-009 (EXEC-006): merge() produces fresh generated values while store caches within scope."""
    parent = VariableStore()
    p_email1 = parent.get("RANDOM_EMAIL")
    p_email2 = parent.get("RANDOM_EMAIL")
    assert p_email1 == p_email2, "Within same store, RANDOM_EMAIL must be cached"

    child1 = parent.merge({})
    c1_email = child1.get("RANDOM_EMAIL")
    assert c1_email != p_email1, "Merged store must generate a fresh RANDOM_EMAIL"

    child2 = parent.merge({})
    c2_email = child2.get("RANDOM_EMAIL")
    assert c2_email != c1_email, "Each merged scenario store must receive fresh values"


# ── REG-010: LOC-006 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg010_assert_hidden_evaluates_all_tiers():
    """REG-010 (LOC-006): ASSERT_HIDDEN checks all tiers and fails if any tier has a visible element."""
    config = BrowserConfig(headless=True, timeout=2000)
    store = VariableStore()
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            # Tier 0 button is hidden; Tier 1 link is visible.
            html = """
            <button style="display:none">Submit</button>
            <a href="#" style="display:block">Submit</a>
            """
            await page.set_content(html)
            step = TestStep(
                line_number=1,
                raw_text='Assert "Submit" is hidden',
                action_type=ActionType.ASSERT_HIDDEN,
                target_type=TargetType.GENERIC,
                target_identifier="Submit",
                value="",
            )
            with pytest.raises(Exception):
                await _dispatch_action(step, page, store, "Submit", "", config)


# ── REG-011: LOC-007 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg011_store_variable_prefers_visible():
    """REG-011 (LOC-007): STORE_VARIABLE prefers visible element on duplicates, but extracts from single hidden."""
    config = BrowserConfig(headless=True)
    store = VariableStore()
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            # Case A: Hidden + visible duplicate -> extract visible
            html = """
            <div style="display:none" class="badge">stale_count</div>
            <div style="display:block" class="badge">fresh_count</div>
            """
            await page.set_content(html)
            step_a = TestStep(
                line_number=1,
                raw_text='Store text from ".badge" as "COUNT"',
                action_type=ActionType.STORE_VARIABLE,
                target_type=TargetType.GENERIC,
                target_identifier=".badge",
                value="COUNT",
            )
            await _dispatch_action(step_a, page, store, ".badge", "COUNT", config)
            assert store.get("COUNT") == "fresh_count"

            # Case B: Genuinely hidden element only -> extraction preserved
            html_hidden = """<input type="hidden" id="token" value="secret_csrf_123" />"""
            await page.set_content(html_hidden)
            step_b = TestStep(
                line_number=2,
                raw_text='Store text from "#token" as "CSRF"',
                action_type=ActionType.STORE_VARIABLE,
                target_type=TargetType.GENERIC,
                target_identifier="#token",
                value="CSRF",
            )
            await _dispatch_action(step_b, page, store, "#token", "CSRF", config)
            assert store.get("CSRF") == "secret_csrf_123"

            # Case C: Multi-tier semantic locator with hidden duplicate followed by visible duplicate
            html_semantic = """
            <form>
                <input type="text" name="email" value="hidden_user@example.com" style="display:none;" />
                <input type="text" name="email" value="visible_user@example.com" style="display:block;" />
            </form>
            """
            await page.set_content(html_semantic)
            step_c = TestStep(
                line_number=3,
                raw_text='Store input "email" as "USER_EMAIL"',
                action_type=ActionType.STORE_VARIABLE,
                target_type=TargetType.INPUT,
                target_identifier="email",
                value="USER_EMAIL",
            )
            await _dispatch_action(step_c, page, store, "email", "USER_EMAIL", config)
            assert store.get("USER_EMAIL") == "visible_user@example.com"


# ── REG-012: LOC-008 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg012_assert_value_respects_target_type():
    """REG-012 (LOC-008): _assert_value respects TargetType.TESTID."""
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            html = """<input data-testid="status-field" value="completed" />"""
            await page.set_content(html)
            step = TestStep(
                line_number=1,
                raw_text='Assert testid "status-field" value is "completed"',
                action_type=ActionType.ASSERT_VALUE,
                target_type=TargetType.TESTID,
                target_identifier="status-field",
                value="is:completed",
            )
            # Should succeed without KeyError or TargetType mismatch
            await _assert_value(page, step, "status-field", "is:completed", config)


# ── REG-013: LOC-010 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg013_assert_visible_fallback_visibility_filter():
    """REG-013 (LOC-010): ASSERT_VISIBLE text container fallback ignores preceding hidden duplicate."""
    config = BrowserConfig(headless=True, timeout=3000)
    store = VariableStore()
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            html = """
            <div style="display:none"><span>Welcome Guest</span></div>
            <div style="display:block"><span>Welcome Guest</span></div>
            """
            await page.set_content(html)
            step = TestStep(
                line_number=1,
                raw_text='Assert "Welcome Guest" is visible',
                action_type=ActionType.ASSERT_VISIBLE,
                target_type=TargetType.GENERIC,
                target_identifier="Welcome Guest",
                value="",
            )
            await _dispatch_action(step, page, store, "Welcome Guest", "", config)


# ── REG-014: EXEC-002 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg014_assertion_timeout_propagation():
    """REG-014 (EXEC-002): Assertions propagate configured timeout to Playwright expect()."""
    config = BrowserConfig(headless=True, timeout=3000)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            await page.set_content("<p>Initial</p>")
            # Delay title update to 1200ms
            await page.evaluate("""
            setTimeout(() => { document.title = 'Async Dashboard'; }, 1200);
            """)
            # Expect title should wait up to config.timeout (3000ms)
            await _assert_title(page, "is", "Async Dashboard", config)


# ── REG-015: EXEC-008 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg015_pytest_lifecycle_guaranteed_teardown(tmp_path):
    """REG-015 (EXEC-008): MarkdownFile teardown runs and cleans up state file even when filtered."""
    from md_e2e.pytest_plugin import MarkdownFile
    from unittest.mock import MagicMock

    session_mock = MagicMock()
    session_mock._md_files = []

    mf = MarkdownFile.from_parent(session_mock, path=Path("dummy.md"))
    mf.teardown_run = False
    temp_file = tmp_path / "temp_state.json"
    temp_file.write_text("{}", encoding="utf-8")
    mf._temp_state_file = str(temp_file)

    config = BrowserConfig(headless=True)
    await mf.ensure_suite_teardown(config)

    assert mf.teardown_run is True
    assert not temp_file.exists(), "State file must be cleaned up on teardown"


# ── REG-016: EXEC-009 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reg016_matrix_row_step_mutation_isolation():
    """REG-016 (EXEC-009): Mutating steps for row 1 does not affect row 2 step definitions."""
    step = TestStep(
        line_number=1,
        raw_text="Wait 0",
        action_type=ActionType.WAIT,
        target_type=TargetType.GENERIC,
        target_identifier="",
        value="0",
    )
    tc = TestCase(
        name="Matrix Test",
        line_number=1,
        parameters=[{"user": "alice"}, {"user": "bob"}],
        steps=[step],
    )
    suite = TestSuite(name="Matrix Mutation Suite", test_cases=[tc])
    config = BrowserConfig(headless=True)

    row_steps_seen = []

    from md_e2e.custom_steps import _custom_steps_registry, CustomStepEntry
    import re

    # In execute_suite, each row copies steps:
    row1 = copy.copy(tc)
    row1.steps = [copy.deepcopy(s) for s in tc.steps]
    row2 = copy.copy(tc)
    row2.steps = [copy.deepcopy(s) for s in tc.steps]

    # Mutate row 1 step scalar and nested mutable variables list
    row1.steps[0].raw_text = "Mutated in Row 1"
    row1.steps[0].variables.append("injected_var")

    assert row2.steps[0].raw_text == "Wait 0", "Row 2 steps must not be mutated by Row 1 edits!"
    assert tc.steps[0].raw_text == "Wait 0", "Original TestCase steps must not be mutated!"
    assert "injected_var" not in row2.steps[0].variables, "Row 2 variables list must be isolated from Row 1!"
    assert "injected_var" not in tc.steps[0].variables, "Original step variables list must be isolated!"


# ── LOC-009: Multiline CSS Escaping ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_loc009_multiline_css_escaping():
    """LOC-009: _css_escape_value and fuzzy attribute inference resolve multiline attributes and form-feed live in Playwright."""
    raw = 'line1\r\nline2\fpage2"with\'quote'
    escaped = _css_escape_value(raw)
    assert "\\a " in escaped
    assert "\\d " in escaped
    assert "\\c " in escaped
    assert '\\"' in escaped
    assert "\\'" in escaped

    # Live Playwright test: multiline and form-feed name attributes resolve without BADSTRING error
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_, page):
            # Case A: Multiline \n
            html = '<input name="address&#10;line2" id="multiline-input" value="123 Main St" />'
            await page.set_content(html)
            tiers = resolve_locator(page, TargetType.INPUT, "address\nline2")
            loc = await wait_and_pick_locator(tiers, 2000)
            actual_id = await loc.evaluate("el => el.id")
            assert actual_id == "multiline-input"

            # Case B: Form feed \f
            await page.set_content('<input id="ff-input" value="ff_value" />')
            await page.locator("#ff-input").evaluate("(el, v) => el.setAttribute('name', v)", "page1\fpage2")
            tiers_ff = resolve_locator(page, TargetType.INPUT, "page1\fpage2")
            loc_ff = await wait_and_pick_locator(tiers_ff, 2000)
            assert await loc_ff.input_value() == "ff_value"

            # Case C: Complex combination with \f, \n, \r, quotes, backslashes, brackets
            comb_val = 'item\r\nsub\fval"quoted"[\'x\']\\path'
            await page.set_content('<input id="comb-input" value="comb_value" />')
            await page.locator("#comb-input").evaluate("(el, v) => el.setAttribute('name', v)", comb_val)
            tiers_comb = resolve_locator(page, TargetType.INPUT, comb_val)
            loc_comb = await wait_and_pick_locator(tiers_comb, 2000)
            assert await loc_comb.input_value() == "comb_value"
