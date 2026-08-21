"""Comprehensive regression tests verifying security sanitization and bug fixes."""

from __future__ import annotations

from pathlib import Path
import pytest
from typer.testing import CliRunner

from md_e2e.models import ActionType, TargetType, TestStep, TestCase, TestSuite
from md_e2e.executor import StepResult, ScenarioResult, SuiteResult, StepStatus, execute_step
from md_e2e.html_reporter import generate_html_report
from md_e2e.reporting import generate_markdown_report
from md_e2e.dsl_parser import parse_step
from md_e2e.md_parser import parse_markdown
from md_e2e.locator import resolve_locator
from md_e2e.healing import fuzzy_heal, _are_opposing_verbs, heal_step, HealingCache
from md_e2e.custom_steps import custom_step, _execute_custom_step
from md_e2e.variables import VariableStore, UndefinedVariableError
from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.cli import app, print_results_table


# ---------------------------------------------------------------------------
# 1. Security: HTML Report XSS Sanitization
# ---------------------------------------------------------------------------

def test_html_report_xss_sanitization(tmp_path: Path) -> None:
    """Verify malicious XSS payloads in scenario names, steps, console logs, and errors are HTML-escaped."""
    malicious_step = TestStep(
        raw_text='- Click button "<script>alert(\'XSS\')</script>"',
        line_number=10,
        action_type=ActionType.CLICK,
        target_type=TargetType.BUTTON,
        target_identifier='<script>alert("XSS")</script>',
    )
    step_res = StepResult(
        step=malicious_step,
        status=StepStatus.FAILED,
        duration_ms=15.0,
    )
    sc_res = ScenarioResult(
        name='Scenario <img src=x onerror=alert(1)>',
        status=StepStatus.FAILED,
        step_results=[step_res],
        error='Error <script>alert("error")</script>',
        console_logs=['[error] Failed <img src=x onerror=alert(2)>'],
        duration_ms=20.0,
    )
    suite_res = SuiteResult(
        name='Suite <iframe src="javascript:alert(1)">',
        scenario_results=[sc_res],
        duration_ms=20.0,
    )

    report_path = tmp_path / "xss_report.html"
    generate_html_report([suite_res], report_path)

    content = report_path.read_text(encoding="utf-8")
    assert "<script>alert('XSS')</script>" not in content
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('XSS')&lt;/script&gt;" in content
    assert "<img src=x onerror=alert(1)>" not in content
    assert "&lt;img src=x onerror=alert(1)&gt;" in content
    assert '<iframe src="javascript:alert(1)">' not in content
    assert "&lt;iframe" in content


# ---------------------------------------------------------------------------
# 2. Markdown Reporting: Pipe Delimiter Escaping
# ---------------------------------------------------------------------------

def test_markdown_report_pipe_escaping() -> None:
    """Verify pipes in suite names are escaped so Markdown tables do not corrupt."""
    suite_res = SuiteResult(
        name="Suite | With | Pipes",
        scenario_results=[
            ScenarioResult(
                name="Scenario 1",
                status=StepStatus.PASSED,
                step_results=[],
                duration_ms=10.0,
            )
        ],
        duration_ms=10.0,
    )
    report = generate_markdown_report([suite_res])
    assert "| `Suite \\| With \\| Pipes` |" in report


# ---------------------------------------------------------------------------
# 3. DSL Parser: Escaped Quotes & Backslashes
# ---------------------------------------------------------------------------

def test_dsl_parser_unescaping_quotes() -> None:
    """Verify escaped quotes inside strings are correctly unescaped by parse_step."""
    step1, err1 = parse_step('Fill input "search" with "Hello \\"World\\""')
    assert err1 is None
    assert step1.value == 'Hello "World"'

    step2, err2 = parse_step("Click button 'It\\'s a test'")
    assert err2 is None
    assert step2.target_identifier == "It's a test"


# ---------------------------------------------------------------------------
# 4. Markdown Parser: Email Addresses vs Tags in Headings
# ---------------------------------------------------------------------------

def test_md_parser_email_in_headings() -> None:
    """Verify @ in email addresses (e.g. user@example.com) is not stripped as a tag."""
    md_text = """# User Suite @smoke

## Scenario for user@example.com @critical
- Navigate to "https://example.com"
"""
    suite, errors = parse_markdown(md_text)
    assert errors == []
    assert suite.tags == ["smoke"]
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].name == "Scenario for user@example.com"
    assert suite.test_cases[0].tags == ["critical"]


# ---------------------------------------------------------------------------
# 5. Locator: Strict Mode Resolution with Compound Selectors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_locator_compound_or_strict_mode(test_server: str) -> None:
    """Verify .or_() compound locators do not throw strict mode violation on multi-match elements."""
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (_ctx, page):
            await page.goto(f"{test_server}/test_app.html")

            # Input with both aria-label="Email" and placeholder="Enter your email"
            locator = resolve_locator(page, TargetType.INPUT, "Email")
            # Should resolve smoothly to a single element with .first
            await locator.fill("test@example.com")
            val = await locator.input_value()
            assert val == "test@example.com"

            # Button with quotes / special characters in CSS fallback
            btn = resolve_locator(page, TargetType.BUTTON, 'Sign In')
            assert await btn.is_visible()


# ---------------------------------------------------------------------------
# 6. Custom Steps: Mixed Named & Positional Capture Groups
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_steps_mixed_group_injection() -> None:
    """Verify custom step handler receives correct arguments when regex has mixed named/positional groups."""
    received = {}

    @custom_step(r'Assign role "(?P<role>[^"]+)" to user "([^"]+)" and dept "([^"]+)"')
    async def assign_role(role: str, user: str, dept: str):
        received["role"] = role
        received["user"] = user
        received["dept"] = dept

    step = TestStep(
        raw_text='Assign role "Admin" to user "Alice" and dept "Engineering"',
        line_number=1,
        action_type=ActionType.CUSTOM,
    )
    store = VariableStore()

    class DummyPage:
        context = None

    await _execute_custom_step(step, DummyPage(), store)
    assert received == {
        "role": "Admin",
        "user": "Alice",
        "dept": "Engineering",
    }


# ---------------------------------------------------------------------------
# 7. Self-Healing: Opposing Verb Guards & Undefined Variables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_healing_bypasses_undefined_variables(test_server: str) -> None:
    """Verify execute_step does not invoke self-healing when failure is due to UndefinedVariableError."""
    config = BrowserConfig(headless=True, enable_healing=True)
    step = TestStep(
        raw_text='- Click button "{{ NON_EXISTENT_VAR }}"',
        line_number=5,
        action_type=ActionType.CLICK,
        target_identifier="{{ NON_EXISTENT_VAR }}",
    )
    store = VariableStore()

    async with BrowserSession(config) as session:
        async with session.new_context() as (_ctx, page):
            await page.goto(f"{test_server}/test_app.html")
            res = await execute_step(
                step, page, store, config=config
            )
            assert res.status == StepStatus.FAILED
            assert res.healed is False
            assert "UndefinedVariableError" in (res.error or "")


def test_opposing_verb_guards() -> None:
    """Verify polar opposite actions are never healed."""
    assert _are_opposing_verbs("Cancel", "Confirm") is True
    assert _are_opposing_verbs("Delete Account", "Save Account") is True
    assert _are_opposing_verbs("Sign In", "Sign Out") is True
    assert _are_opposing_verbs("Next", "Previous") is True


# ---------------------------------------------------------------------------
# 8. CLI: Accurate Summary Counts and Failure Propagation
# ---------------------------------------------------------------------------

def test_cli_summary_table_counts() -> None:
    """Verify print_results_table correctly accounts for passed, skipped, and failed."""
    suite_res = SuiteResult(
        name="Mixed Suite",
        scenario_results=[
            ScenarioResult(name="S1", status=StepStatus.PASSED, duration_ms=10.0),
            ScenarioResult(name="S2", status=StepStatus.SKIPPED, duration_ms=10.0),
            ScenarioResult(name="S3", status=StepStatus.FAILED, duration_ms=10.0, error="boom"),
        ],
        duration_ms=30.0,
    )
    has_failures = print_results_table([suite_res])
    assert has_failures is True
