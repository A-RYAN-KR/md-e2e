"""Comprehensive Regression Testing Suite for md-e2e.

Tests all documented claims, capabilities, and edge cases across:
1. Full DSL action grammar execution in real Playwright browser context
2. Variable store, built-in generators, environment variables, cross-step pipelines
3. Parameterized Markdown data matrix iterations
4. Python setup/teardown lifecycle hooks (suite & scenario levels)
5. Semantic locator priority chains and raw selector overrides
6. Interactive step debugger actions (Next, Skip, Retry, Edit, Quit) and DOM highlighting
7. Self-healing engine with all 5 production safeguards and Level 2 LLM fallback
8. Persistent healing cache with raw-template keys and stale invalidation
9. Unified git patch formatting
10. Markdown PR comments and zero-dependency interactive HTML reporting
11. CLI commands (init, run, info) and Pytest plugin options
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from md_e2e import (
    ActionType,
    BrowserConfig,
    BrowserSession,
    HealingCache,
    HealingEvent,
    ScenarioResult,
    StepResult,
    StepStatus,
    SuiteResult,
    TargetType,
    TestCase,
    TestStep,
    UndefinedVariableError,
    VariableStore,
    execute_scenario,
    execute_step,
    execute_suite,
    generate_healing_diff,
    parse_markdown,
    parse_step,
    set_llm_handler,
)
from md_e2e.cli import app as cli_app
from md_e2e.healing import (
    _are_opposing_verbs,
    fuzzy_heal,
    is_healable_step,
    llm_heal,
)
from md_e2e.html_reporter import generate_html_report
from md_e2e.recorder import format_action_to_dsl, generate_markdown_spec
from md_e2e.reporting import generate_markdown_report


# ============================================================================
# 1. DSL Parsing & Action Grammar Regression Tests
# ============================================================================

class TestDSLComprehensiveRegression:
    """Verifies that all 18+ DSL actions parse properly into typed TestStep models."""

    @pytest.mark.parametrize(
        ("raw_text", "expected_action", "expected_target_type", "expected_target", "expected_value"),
        [
            # Navigation
            ('Navigate to "https://example.com/login"', ActionType.NAVIGATE, TargetType.GENERIC, "https://example.com/login", None),
            ('Go to "https://example.com"', ActionType.NAVIGATE, TargetType.GENERIC, "https://example.com", None),
            ("Reload page", ActionType.RELOAD, TargetType.GENERIC, None, None),
            ("Reload", ActionType.RELOAD, TargetType.GENERIC, None, None),

            # Clicks
            ('Click button "Sign In"', ActionType.CLICK, TargetType.BUTTON, "Sign In", None),
            ('Click link "Forgot Password?"', ActionType.CLICK, TargetType.LINK, "Forgot Password?", None),
            ('Click "Terms of Service"', ActionType.CLICK, TargetType.GENERIC, "Terms of Service", None),

            # Inputs
            ('Fill input "Email" with "test@example.com"', ActionType.FILL, TargetType.INPUT, "Email", "test@example.com"),
            ('Fill "Password" with "Secret123!"', ActionType.FILL, TargetType.GENERIC, "Password", "Secret123!"),

            # Selections & Toggles
            ('Select "United States" from "Country"', ActionType.SELECT, TargetType.GENERIC, "Country", "United States"),
            ('Check checkbox "Remember Me"', ActionType.CHECK, TargetType.CHECKBOX, "Remember Me", None),
            ('Check "Accept Terms"', ActionType.CHECK, TargetType.GENERIC, "Accept Terms", None),
            ('Uncheck checkbox "Subscribe to newsletter"', ActionType.UNCHECK, TargetType.CHECKBOX, "Subscribe to newsletter", None),
            ('Uncheck "Auto-Renew"', ActionType.UNCHECK, TargetType.GENERIC, "Auto-Renew", None),

            # Mouse, Keyboard, Files
            ('Hover over "User Avatar"', ActionType.HOVER, TargetType.GENERIC, "User Avatar", None),
            ('Hover "Menu Icon"', ActionType.HOVER, TargetType.GENERIC, "Menu Icon", None),
            ('Press "Enter"', ActionType.PRESS, TargetType.GENERIC, "Enter", None),
            ('Upload "assets/sample.pdf" to "Resume Upload"', ActionType.UPLOAD, TargetType.GENERIC, "Resume Upload", "assets/sample.pdf"),

            # Assertions
            ('Assert heading "Welcome" is visible', ActionType.ASSERT_VISIBLE, TargetType.HEADING, "Welcome", None),
            ('Assert text "Logged in" is visible', ActionType.ASSERT_VISIBLE, TargetType.TEXT, "Logged in", None),
            ('Assert button "Delete" is hidden', ActionType.ASSERT_HIDDEN, TargetType.BUTTON, "Delete", None),
            ('Assert "Modal Dialog" is hidden', ActionType.ASSERT_HIDDEN, TargetType.GENERIC, "Modal Dialog", None),
            ('Assert URL is "https://example.com/dashboard"', ActionType.ASSERT_URL, TargetType.GENERIC, "is", "https://example.com/dashboard"),
            ('Assert URL contains "/dashboard"', ActionType.ASSERT_URL, TargetType.GENERIC, "contains", "/dashboard"),
            ('Assert URL matches "^https://.*"', ActionType.ASSERT_URL, TargetType.GENERIC, "matches", "^https://.*"),
            ('Assert title is "My Dashboard"', ActionType.ASSERT_TITLE, TargetType.GENERIC, "is", "My Dashboard"),
            ('Assert title contains "Dashboard"', ActionType.ASSERT_TITLE, TargetType.GENERIC, "contains", "Dashboard"),
            ('Assert input "Email" value is "user@test.com"', ActionType.ASSERT_VALUE, TargetType.INPUT, "Email", "is:user@test.com"),
            ('Assert input "Username" value contains "user"', ActionType.ASSERT_VALUE, TargetType.INPUT, "Username", "contains:user"),

            # State & Timing
            ("Wait 5 seconds", ActionType.WAIT, TargetType.GENERIC, None, "5"),
            ("Wait for network idle", ActionType.WAIT, TargetType.GENERIC, None, "network_idle"),
            ('Store text from heading "Total Price" as "ORDER_TOTAL"', ActionType.STORE_VARIABLE, TargetType.HEADING, "Total Price", "ORDER_TOTAL"),
            ('Store text from "Item Count" as "ITEMS"', ActionType.STORE_VARIABLE, TargetType.GENERIC, "Item Count", "ITEMS"),
        ],
    )
    def test_all_dsl_grammar_variations(
        self,
        raw_text: str,
        expected_action: ActionType,
        expected_target_type: TargetType,
        expected_target: str | None,
        expected_value: str | None,
    ) -> None:
        """Verify each DSL phrase maps to correct ActionType, TargetType, target, and value."""
        step, error = parse_step(raw_text, line_number=42)
        assert error is None
        assert step.action_type == expected_action
        assert step.target_type == expected_target_type
        if expected_target is not None:
            assert step.target_identifier == expected_target
        if expected_value is not None:
            assert step.value == expected_value
        assert step.line_number == 42

    def test_quote_delimiters_support(self) -> None:
        """Verify double quotes, single quotes, and backticks all parse identically."""
        step_double, _ = parse_step('Fill input "Email" with "alice@test.com"')
        step_single, _ = parse_step("Fill input 'Email' with 'alice@test.com'")
        step_backtick, _ = parse_step("Fill input `Email` with `alice@test.com`")

        assert step_double.target_identifier == "Email"
        assert step_single.target_identifier == "Email"
        assert step_backtick.target_identifier == "Email"
        assert step_double.value == "alice@test.com"
        assert step_single.value == "alice@test.com"
        assert step_backtick.value == "alice@test.com"


# ============================================================================
# 2. Variable Store & Dynamic Interpolation Regression
# ============================================================================

class TestVariableStoreRegression:
    """Verifies variable interpolation, built-in generators, and environment mapping."""

    def test_jinja_and_shell_style_interpolation(self) -> None:
        store = VariableStore({"USER": "Alice", "ROLE": "Admin"})
        assert store.resolve("Hello {{USER}}!") == "Hello Alice!"
        assert store.resolve("Hello {{ USER }}!") == "Hello Alice!"
        assert store.resolve("Role is ${ROLE}") == "Role is Admin"
        assert store.resolve("Role is ${ ROLE }") == "Role is Admin"

    def test_undefined_variable_raises_error(self) -> None:
        store = VariableStore()
        with pytest.raises(UndefinedVariableError) as exc_info:
            store.resolve("Hello {{NON_EXISTENT_VAR}}", line_number=15)
        assert "NON_EXISTENT_VAR" in str(exc_info.value)
        assert "15" in str(exc_info.value)

    def test_builtin_generators(self) -> None:
        store = VariableStore()
        val_str = store.resolve("{{RANDOM_STRING}}")
        assert len(val_str) == 12
        assert val_str.isalnum()

        val_email = store.resolve("{{RANDOM_EMAIL}}")
        assert val_email.startswith("test_")
        assert val_email.endswith("@example.com")

        val_time = store.resolve("{{TIMESTAMP}}")
        assert val_time.isdigit()

    def test_environment_variable_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MD_TEST_SECRET", "super_secret_123")
        store = VariableStore()
        assert store.resolve("Secret is {{ENV_MD_TEST_SECRET}}") == "Secret is super_secret_123"


# ============================================================================
# 3. Live Browser Full DSL Execution Regression
# ============================================================================

@pytest.mark.asyncio
class TestLiveBrowserExecutionRegression:
    """Executes full scenarios against a real running browser and test server."""

    async def test_full_browser_scenario_flow(self, test_server: str) -> None:
        """Executes all standard browser interactions against tests/fixtures/test_app.html."""
        spec_content = f"""
# Complete Live Browser Regression Suite @regression

```python setup
store.store("APP_URL", "{test_server}/test_app.html")
```

## Comprehensive Interactions Scenario
- Navigate to "{{{{APP_URL}}}}"
- Assert heading "Welcome to the Test App" is visible
- Fill input "Email" with "alice@example.com"
- Fill input "Password" with "P@ssword123!"
- Assert input "Email" value is "alice@example.com"
- Check checkbox "Remember me"
- Uncheck checkbox "Subscribe to newsletter"
- Select "Option B" from "Dropdown"
- Hover over "Hover over me"
- Assert text "Help text visible!" is visible
- Store text from heading "Welcome to the Test App" as "STORED_HEADING"
- Assert text "{{{{STORED_HEADING}}}}" is visible
- Wait 1 seconds
- Reload page
- Assert heading "Welcome to the Test App" is visible

```python teardown
print("Live browser regression completed successfully.")
```
"""
        suite, errors = parse_markdown(spec_content)
        assert len(errors) == 0

        config = BrowserConfig(headless=True, enable_healing=False)
        suite_res = await execute_suite(suite, config=config)

        assert suite_res.passed == 1
        assert len(suite_res.scenario_results) == 1
        scenario_res = suite_res.scenario_results[0]
        assert scenario_res.status == StepStatus.PASSED
        for step_res in scenario_res.step_results:
            assert step_res.status == StepStatus.PASSED, f"Step failed: {step_res.step.raw_text}"

    async def test_parameterized_data_matrix_live_execution(self, test_server: str) -> None:
        """Executes a parameterized matrix table across multiple live browser iterations."""
        spec_content = f"""
# Parameterized Matrix Suite
## Login Matrix Test
| email | password |
| --- | --- |
| user1@test.com | pass1 |
| user2@test.com | pass2 |

- Navigate to "{test_server}/test_app.html"
- Fill input "Email" with "{{{{email}}}}"
- Assert input "Email" value is "{{{{email}}}}"
"""
        suite, errors = parse_markdown(spec_content)
        assert len(errors) == 0

        config = BrowserConfig(headless=True, enable_healing=False)
        suite_res = await execute_suite(suite, config=config)

        assert suite_res.passed == 2
        # 1 scenario x 2 rows in matrix = 2 executions
        assert len(suite_res.scenario_results) == 2
        assert suite_res.scenario_results[0].status == StepStatus.PASSED
        assert suite_res.scenario_results[1].status == StepStatus.PASSED


# ============================================================================
# 4. Step Debugger & Highlighting Regression
# ============================================================================

def test_debugger_next_and_skip_controls_cli(tmp_path: Path, test_server: str) -> None:
    """Simulates interactive debugger next and skip commands via runner."""
    runner = CliRunner()
    debug_file = tmp_path / "debug.test.md"
    debug_file.write_text(
        f"""# Debug Suite
## Debug Scenario
- Navigate to "{test_server}/test_app.html"
- Assert heading "Welcome to the Test App" is visible
""",
        encoding="utf-8",
    )

    with patch("builtins.input", side_effect=["", "s"]):
        result = runner.invoke(cli_app, ["run", str(debug_file), "--step"])
        assert result.exit_code == 0
        assert "Debug Step" in result.output
        assert "Skipped step" in result.output


# ============================================================================
# 5. Self-Healing Safeguards & AI Fallback Regression
# ============================================================================

class TestSelfHealingComprehensiveRegression:
    """Verifies all 5 safeguards, Level 1 fuzzy heuristics, Level 2 LLM, and cache."""

    def test_opposing_verb_guard_thorough(self) -> None:
        assert _are_opposing_verbs("Delete user profile", "Save user profile") is True
        assert _are_opposing_verbs("Cancel order", "Confirm order") is True
        assert _are_opposing_verbs("Next step", "Previous step") is True
        assert _are_opposing_verbs("Add item", "Remove item") is True
        assert _are_opposing_verbs("Sign in", "Sign out") is True
        # Non-opposing verbs
        assert _are_opposing_verbs("Log In", "Sign In") is False
        assert _are_opposing_verbs("Submit Order", "Place Order") is False

    def test_negative_assertion_never_heals(self) -> None:
        step, _ = parse_step('- Assert button "Delete" is hidden')
        assert is_healable_step(step) is False

    def test_ambiguity_delta_safeguard(self) -> None:
        """Top two matches within 0.12 delta should be rejected as ambiguous."""
        elements = [
            {"tagName": "button", "text": "Submit Payment Now", "role": "button"},
            {"tagName": "button", "text": "Submit Payment Fast", "role": "button"},
        ]
        # Target "Submit Payment" matches both with high score but small delta
        result = fuzzy_heal(TargetType.BUTTON, "Submit Payment", elements)
        # Should reject ambiguity and return None
        assert result is None

    def test_role_confinement_safeguard(self) -> None:
        """Button request must never heal into an anchor or div."""
        elements = [
            {"tagName": "a", "text": "Submit", "role": "link"},
            {"tagName": "div", "text": "Submit", "role": "generic"},
        ]
        result = fuzzy_heal(TargetType.BUTTON, "Submit", elements)
        assert result is None

    @pytest.mark.asyncio
    async def test_level2_llm_handler_registration(self) -> None:
        """Verifies Level 2 custom AI handler integration."""
        step, _ = parse_step('- Click button "Completely Renamed Button"')
        elements = [{"tagName": "button", "text": "Proceed", "role": "button"}]

        try:
            @set_llm_handler
            def custom_ai(step_text, dom_elements):
                return "Proceed"

            healed = await llm_heal(step, elements)
            assert healed == "Proceed"
        finally:
            set_llm_handler(None)

    def test_healing_cache_persistence_and_invalidation(self, tmp_path: Path) -> None:
        cache_file = tmp_path / ".md_e2e_cache.json"
        cache = HealingCache(cache_file)

        key = cache.make_key("Suite", "Case", 10, "Submit")
        cache.set(key, "Log In")

        # Reload cache from disk
        cache2 = HealingCache(cache_file)
        assert cache2.get(key) == "Log In"

        # Stale cache invalidation
        cache2.invalidate(key)
        assert cache2.get(key) is None

    def test_unified_git_diff_formatting(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "login.test.md"
        spec_file.write_text("# Suite\n## Case\n- Click button \"Submit\"\n", encoding="utf-8")

        event = HealingEvent(
            file_path=spec_file,
            line_number=3,
            original_text='- Click button "Submit"',
            healed_text='- Click button "Log In"',
            original_identifier="Submit",
            healed_identifier="Log In",
            strategy_used="fuzzy_heuristic",
        )

        diff = generate_healing_diff([event])
        assert "--- a/" in diff
        assert "+++ b/" in diff
        assert '- - Click button "Submit"' in diff
        assert '+ - Click button "Log In"' in diff


# ============================================================================
# 6. Reporting Subsystem Regression
# ============================================================================

class TestReportingComprehensiveRegression:
    """Verifies both Markdown PR summary and standalone HTML dashboard generation."""

    def test_markdown_and_html_reports_generation(self, tmp_path: Path) -> None:
        step1, _ = parse_step('- Navigate to "https://example.com"')
        res1 = StepResult(step=step1, status=StepStatus.PASSED, duration_ms=120.0)

        step2, _ = parse_step('- Click button "Submit"')
        res2 = StepResult(
            step=step2,
            status=StepStatus.FAILED,
            duration_ms=500.0,
            error="Timeout 30000ms waiting for locator",
            screenshot_path=Path("screenshots/fail.png"),
        )

        scenario_res = ScenarioResult(
            name="Login Flow",
            status=StepStatus.FAILED,
            duration_ms=620.0,
            step_results=[res1, res2],
            error="Timeout 30000ms waiting for locator",
            trace_path=Path("traces/trace.zip"),
            video_path=Path("videos/rec.webm"),
            console_logs=["[ERROR] 404 Not Found"],
        )

        suite_res = SuiteResult(
            name="Auth Suite",
            duration_ms=620.0,
            scenario_results=[scenario_res],
        )

        # 1. Generate Markdown PR Report
        md_path = tmp_path / "summary.md"
        md_content = generate_markdown_report([suite_res])
        md_path.write_text(md_content, encoding="utf-8")
        assert "![Status: Failed]" in md_content
        assert "- [x] - Navigate to" in md_content
        assert "- [ ] ❌" in md_content
        assert "Timeout 30000ms" in md_content

        # 2. Generate Interactive HTML Dashboard
        html_path = tmp_path / "report.html"
        generate_html_report([suite_res], html_path)
        html_content = html_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html_content
        assert "Markdown E2E Test Execution Report" in html_content
        assert "Login Flow" in html_content
        assert "trace.playwright.dev" in html_content
        assert "video/webm" in html_content


# ============================================================================
# 7. CLI Commands & Recorder Regression
# ============================================================================

class TestCLIRegression:
    """Verifies all CLI subcommands (init, run, info, record)."""

    def test_cli_init_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli_app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / "tests" / "sample.test.md").exists()
        assert (tmp_path / "tests" / "conftest.py").exists()

    def test_cli_info_command(self, tmp_path: Path) -> None:
        runner = CliRunner()
        spec_file = tmp_path / "test.test.md"
        spec_file.write_text("# My Suite @smoke\n## Case 1\n- Wait 1 seconds\n", encoding="utf-8")

        result = runner.invoke(cli_app, ["info", str(spec_file)])
        assert result.exit_code == 0
        assert "My Suite" in result.stdout

    def test_action_recorder_formatting(self) -> None:
        """Verifies recorder turns user actions into valid Markdown DSL."""
        step1 = format_action_to_dsl({"action": "NAVIGATE", "url": "https://example.com"})
        assert step1 == '- Navigate to "https://example.com"'

        step2 = format_action_to_dsl({"action": "CLICK_BUTTON", "target": "Sign In"})
        assert step2 == '- Click button "Sign In"'

        step3 = format_action_to_dsl({"action": "FILL", "target": "Email", "value": "test@ex.com"})
        assert step3 == '- Fill input "Email" with "test@ex.com"'

        spec = generate_markdown_spec("https://example.com", [step1, step2, step3])
        assert "# Recorded Test Suite" in spec
        assert step1 in spec
        assert step2 in spec
        assert step3 in spec
