"""Regression and verification tests for all 28 bug fixes."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

import md_e2e
from md_e2e.models import ActionType, TargetType, TestStep, TestCase, TestSuite
from md_e2e.executor import StepStatus
from md_e2e.variables import VariableStore, UndefinedVariableError
from md_e2e.dsl_parser import parse_step, _extract_variables, _strip_quotes
from md_e2e.locator import _css_escape_value
from md_e2e.healing import (
    _HEALABLE_ACTIONS,
    _replace_target_identifier,
    generate_healing_diff,
    HealingEvent,
)
from md_e2e.reporting import generate_markdown_report
from md_e2e.html_reporter import generate_html_report
from md_e2e.recorder import format_action_to_dsl
from md_e2e.cli import find_test_files, _format_step_error
from md_e2e.custom_steps import custom_step, clear_custom_steps, _custom_steps_registry
from md_e2e.executor import _css_escape_value as exec_css_escape


def test_bug1_version_match():
    """BUG-1: md_e2e.__version__ must match pyproject.toml version (0.3.0)."""
    assert md_e2e.__version__ == "0.3.0"


def test_bug2_hook_trusted_code():
    """BUG-2: _run_hook treats code as trusted Python (no fake sandbox)."""
    from md_e2e.executor import _run_hook
    from md_e2e.browser import BrowserConfig
    from unittest.mock import MagicMock

    mock_page = MagicMock()
    store = VariableStore()
    config = BrowserConfig()

    # The code should be able to access standard builtins without raising NameError
    trusted_code = "import os\nstore.store('is_trusted', 'yes')"
    asyncio.run(_run_hook(trusted_code, mock_page, store, config))
    assert store.get("is_trusted") == "yes"


def test_bug3_angle_brackets_safe_html_and_params():
    """BUG-3: HTML tags like <div> or <input> must not raise UndefinedVariableError when resolving."""
    store = VariableStore({"name": "Alice", "sku": "SKU-123"})
    # Normal variables work
    assert store.resolve("Hello {{name}}") == "Hello Alice"
    assert store.resolve("Hello ${name}") == "Hello Alice"

    # Data matrix table parameters work
    assert store.resolve("Item <sku>") == "Item SKU-123"

    # HTML tags in text do not raise errors when undefined
    html_text = "Click the <div> element and check <input> field"
    resolved = store.resolve(html_text)
    assert resolved == html_text


def test_bug5_assert_title_not_healable():
    """BUG-5: ActionType.ASSERT_TITLE must NOT be in _HEALABLE_ACTIONS."""
    assert ActionType.ASSERT_TITLE not in _HEALABLE_ACTIONS


def test_bug6_variable_store_has_case_insensitive():
    """BUG-6: VariableStore.has() should have case-insensitive fallback matching get()."""
    store = VariableStore({"USER_NAME": "Bob"})
    assert store.has("USER_NAME") is True
    assert store.has("user_name") is True
    assert store.has("User_Name") is True
    assert store.get("user_name") == "Bob"


def test_bug8_replace_target_identifier_safe_chars():
    """BUG-8: _replace_target_identifier should handle regex special chars in new_id."""
    raw = 'Click button "old_target"'
    new_id = r"new\1$target+special"
    replaced = _replace_target_identifier(raw, "old_target", new_id)
    assert replaced == f'Click button "{new_id}"'


def test_bug9_and_23_css_escape():
    """BUG-9 & BUG-23: CSS escape helper handles quotes, brackets, backslashes."""
    assert _css_escape_value('test"value') == 'test\\"value'
    assert _css_escape_value("test'value") == "test\\'value"
    assert _css_escape_value("test]value") == "test\\]value"
    assert _css_escape_value("test\\value") == "test\\\\value"
    assert exec_css_escape('test"value') == 'test\\"value'


def test_bug10_reporting_skipped_not_counted_as_passed():
    """BUG-10: SKIPPED scenarios must not be counted as PASSED in reports."""
    from md_e2e.executor import ScenarioResult, SuiteResult

    sc_passed = ScenarioResult(name="S1", status=StepStatus.PASSED, duration_ms=10.0)
    sc_skipped = ScenarioResult(name="S2", status=StepStatus.SKIPPED, duration_ms=0.0)
    sc_failed = ScenarioResult(name="S3", status=StepStatus.FAILED, duration_ms=15.0, error="boom")

    suite = SuiteResult(name="Suite", scenario_results=[sc_passed, sc_skipped, sc_failed])
    md_report = generate_markdown_report([suite])

    # 1 passed, 1 failed, 1 skipped -> Total 3 tests, 1 passed
    assert "`1/3` Scenarios Passed" in md_report
    assert "| `Suite` | 3 | 1 | 1 | 0 |" in md_report


def test_bug12_random_generators_across_stores():
    """BUG-12: Built-in RANDOM_* generators should return fresh values across new stores."""
    store1 = VariableStore()
    val1 = store1.get("RANDOM_STRING")
    email1 = store1.get("RANDOM_EMAIL")

    store2 = VariableStore()
    val2 = store2.get("RANDOM_STRING")
    email2 = store2.get("RANDOM_EMAIL")

    assert val1 != val2
    assert email1 != email2

    # Intra-store consistency (cached per store lifecycle)
    assert store1.get("RANDOM_STRING") == val1
    assert store1.get("RANDOM_EMAIL") == email1


def test_bug17_dx1_clear_custom_steps():
    """BUG-17 & DX-1: clear_custom_steps() clears the global registry."""
    @custom_step(r"Custom test step unique 12345")
    def my_handler(page):
        pass

    assert len(_custom_steps_registry) > 0
    clear_custom_steps()
    assert len(_custom_steps_registry) == 0


def test_bug18_find_test_files_ignores_readme(tmp_path: Path):
    """BUG-18: find_test_files should ignore non-test docs like README.md, CHANGELOG.md."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "README.md").write_text("# Doc", encoding="utf-8")
    (tests_dir / "CHANGELOG.md").write_text("# Log", encoding="utf-8")
    (tests_dir / "valid.test.md").write_text("# Test", encoding="utf-8")

    files = find_test_files(tests_dir)
    assert len(files) == 1
    assert files[0].name == "valid.test.md"


def test_bug19_recorder_press_action():
    """BUG-19: format_action_to_dsl formats PRESS actions to DSL."""
    dsl = format_action_to_dsl({"action": "PRESS", "target": "Enter"})
    assert dsl == '- Press "Enter"'


def test_bug20_noise_marker_precision():
    """BUG-20: Legitimate error containing 'waiting for' is not stripped."""
    err = "Custom application error: waiting for user input"
    formatted = _format_step_error(err)
    assert "waiting for user input" in formatted


def test_bug22_assert_visibility_comparison_mode():
    """BUG-22: assert_visible and assert_hidden have comparison_mode set."""
    step, _ = parse_step('Assert heading "Welcome" is visible')
    assert step.comparison_mode == "is"

    step_hidden, _ = parse_step('Assert button "Cancel" is hidden')
    assert step_hidden.comparison_mode == "is"


def test_bug25_browser_config_llm_timeout():
    """BUG-25: BrowserConfig has configurable llm_timeout."""
    config = md_e2e.BrowserConfig(llm_timeout=25)
    assert config.llm_timeout == 25


def test_bug26_git_apply_diff_header():
    """BUG-26: generate_healing_diff includes diff --git header."""
    ev = HealingEvent(
        file_path=Path("tests/login.test.md"),
        line_number=10,
        original_text='- Click button "Old"',
        healed_text='- Click button "New"',
        original_identifier="Old",
        healed_identifier="New",
        strategy_used="fuzzy_heuristic",
    )
    diff = generate_healing_diff([ev])
    assert "diff --git a/tests/login.test.md b/tests/login.test.md" in diff
    assert "--- a/tests/login.test.md" in diff
    assert "+++ b/tests/login.test.md" in diff


def test_bug28_strip_quotes_unescape():
    """BUG-28: _strip_quotes unescapes escaped quotes and backslashes properly."""
    assert _strip_quotes('"Hello \\"World\\""') == 'Hello "World"'
    assert _strip_quotes("'Hello \\'World\\''") == "Hello 'World'"
    assert _strip_quotes('`Hello \\`World\\``') == "Hello `World`"
    assert _strip_quotes('"No quotes"') == "No quotes"
