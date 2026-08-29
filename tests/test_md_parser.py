"""Unit tests for md_e2e.md_parser — full Markdown → TestSuite parsing.

Covers:
- Header / scenario / step extraction
- Tag extraction from headings
- Suite-level vs. scenario-level code blocks
- Free-text description capture
- Data table parameterisation
- Checklist item detection
- Error reporting with line numbers
- File path attachment
- End-to-end realistic fixture parsing
"""

import pytest
from pathlib import Path

from md_e2e.md_parser import parse_markdown, parse_markdown_file
from md_e2e.models import ActionType, TargetType


# ═══════════════════════════════════════════════════════════════════════════
# Basic structure
# ═══════════════════════════════════════════════════════════════════════════


class TestBasicStructure:
    def test_h1_becomes_suite_name(self):
        suite, _ = parse_markdown("# My Test Suite\n")
        assert suite.name == "My Test Suite"

    def test_h2_becomes_test_case(self):
        md = "# Suite\n\n## Scenario One\n\n- Click \"A\"\n"
        suite, _ = parse_markdown(md)
        assert len(suite.test_cases) == 1
        assert suite.test_cases[0].name == "Scenario One"

    def test_multiple_scenarios(self):
        md = (
            "# Suite\n\n"
            "## Scenario A\n\n- Click \"X\"\n\n"
            "## Scenario B\n\n- Click \"Y\"\n"
        )
        suite, _ = parse_markdown(md)
        assert len(suite.test_cases) == 2
        assert suite.test_cases[0].name == "Scenario A"
        assert suite.test_cases[1].name == "Scenario B"

    def test_steps_attached_to_correct_scenario(self):
        md = (
            "# S\n\n"
            "## A\n\n- Click \"1\"\n- Click \"2\"\n\n"
            "## B\n\n- Click \"3\"\n"
        )
        suite, _ = parse_markdown(md)
        assert len(suite.test_cases[0].steps) == 2
        assert len(suite.test_cases[1].steps) == 1

    def test_no_h1_uses_fallback_name(self):
        md = "## Scenario\n\n- Click \"A\"\n"
        suite, _ = parse_markdown(md)
        assert suite.name == "Untitled Suite"

    def test_no_h1_uses_filename_if_available(self):
        md = "## Scenario\n\n- Click \"A\"\n"
        suite, _ = parse_markdown(md, file_path="tests/login.md")
        assert suite.name == "login"


# ═══════════════════════════════════════════════════════════════════════════
# Tags
# ═══════════════════════════════════════════════════════════════════════════


class TestTagExtraction:
    def test_suite_tags(self):
        suite, _ = parse_markdown("# Login Tests @smoke @regression\n")
        assert suite.name == "Login Tests"
        assert "smoke" in suite.tags
        assert "regression" in suite.tags

    def test_scenario_tags(self):
        md = "# S\n\n## Happy Path @happy @e2e\n\n- Click \"A\"\n"
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert tc.name == "Happy Path"
        assert "happy" in tc.tags
        assert "e2e" in tc.tags

    def test_no_tags(self):
        suite, _ = parse_markdown("# Clean Title\n")
        assert suite.tags == []


# ═══════════════════════════════════════════════════════════════════════════
# Description capture
# ═══════════════════════════════════════════════════════════════════════════


class TestDescriptionCapture:
    def test_suite_description(self):
        md = (
            "# Suite\n\n"
            "This suite tests the login flow.\n\n"
            "## Scenario\n\n- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        assert suite.description is not None
        assert "login flow" in suite.description

    def test_scenario_description(self):
        md = (
            "# S\n\n"
            "## Login\n\n"
            "The user should be able to login.\n\n"
            "- Navigate to \"https://example.com\"\n"
        )
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert tc.description is not None
        assert "able to login" in tc.description

    def test_description_stops_at_first_step(self):
        md = (
            "# S\n\n"
            "## Scenario\n\n"
            "Description paragraph.\n\n"
            "- Click \"A\"\n\n"
            "This is NOT description.\n\n"
        )
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert tc.description == "Description paragraph."


# ═══════════════════════════════════════════════════════════════════════════
# Code blocks (setup / teardown)
# ═══════════════════════════════════════════════════════════════════════════


class TestCodeBlocks:
    def test_suite_level_setup(self):
        md = (
            "# Suite\n\n"
            "```python setup\n"
            "BASE_URL = 'https://example.com'\n"
            "```\n\n"
            "## Scenario\n\n- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        assert suite.suite_setup_code is not None
        assert "BASE_URL" in suite.suite_setup_code

    def test_suite_level_teardown(self):
        md = (
            "# Suite\n\n"
            "```python teardown\n"
            "cleanup()\n"
            "```\n\n"
            "## Scenario\n\n- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        assert suite.suite_teardown_code is not None
        assert "cleanup" in suite.suite_teardown_code

    def test_scenario_level_setup(self):
        md = (
            "# S\n\n"
            "## Scenario\n\n"
            "```python setup\n"
            "login_as('admin')\n"
            "```\n\n"
            "- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert tc.setup_code is not None
        assert "login_as" in tc.setup_code

    def test_scenario_level_teardown(self):
        md = (
            "# S\n\n"
            "## Scenario\n\n"
            "- Click \"A\"\n\n"
            "```python teardown\n"
            "logout()\n"
            "```\n"
        )
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert tc.teardown_code is not None
        assert "logout" in tc.teardown_code

    def test_non_python_blocks_ignored(self):
        md = (
            "# S\n\n"
            "```javascript\n"
            "console.log('hi')\n"
            "```\n\n"
            "## Scenario\n\n- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        assert suite.suite_setup_code is None


# ═══════════════════════════════════════════════════════════════════════════
# Data table parameterisation
# ═══════════════════════════════════════════════════════════════════════════


class TestDataTable:
    def test_table_parsed_as_parameters(self):
        md = (
            "# S\n\n"
            "## Param Test\n\n"
            "| user    | pass   |\n"
            "|---------|--------|\n"
            "| alice   | abc123 |\n"
            "| bob     | xyz789 |\n\n"
            "- Fill \"User\" with \"{{user}}\"\n"
        )
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        assert len(tc.parameters) == 2
        assert tc.parameters[0]["user"] == "alice"
        assert tc.parameters[0]["pass"] == "abc123"
        assert tc.parameters[1]["user"] == "bob"

    def test_empty_table_no_error(self):
        md = (
            "# S\n\n"
            "## No Data\n\n"
            "| col |\n"
            "|-----|\n\n"
            "- Click \"A\"\n"
        )
        suite, _ = parse_markdown(md)
        assert suite.test_cases[0].parameters == []


# ═══════════════════════════════════════════════════════════════════════════
# Checklist items
# ═══════════════════════════════════════════════════════════════════════════


class TestChecklistItems:
    def test_unchecked_item(self):
        md = '# S\n\n## T\n\n- [ ] Click "A"\n'
        suite, _ = parse_markdown(md)
        step = suite.test_cases[0].steps[0]
        assert step.is_checklist_item is True
        assert step.is_checked is False
        assert step.action_type == ActionType.CLICK

    def test_checked_item(self):
        md = '# S\n\n## T\n\n- [x] Navigate to "https://example.com"\n'
        suite, _ = parse_markdown(md)
        step = suite.test_cases[0].steps[0]
        assert step.is_checklist_item is True
        assert step.is_checked is True
        assert step.action_type == ActionType.NAVIGATE

    def test_mixed_items(self):
        md = (
            "# S\n\n## T\n\n"
            '- [x] Click "A"\n'
            '- [ ] Click "B"\n'
            '- Click "C"\n'
        )
        suite, _ = parse_markdown(md)
        steps = suite.test_cases[0].steps
        assert steps[0].is_checklist_item is True and steps[0].is_checked is True
        assert steps[1].is_checklist_item is True and steps[1].is_checked is False
        assert steps[2].is_checklist_item is False


# ═══════════════════════════════════════════════════════════════════════════
# Line numbers (1-indexed)
# ═══════════════════════════════════════════════════════════════════════════


class TestLineNumbers:
    def test_scenario_line_number(self):
        md = "# Suite\n\n## Scenario\n\n- Click \"A\"\n"
        suite, _ = parse_markdown(md)
        tc = suite.test_cases[0]
        # ## Scenario is on line 3 (1-indexed)
        assert tc.line_number == 3

    def test_step_line_numbers_positive(self):
        md = "# S\n\n## T\n\n- Click \"A\"\n- Click \"B\"\n"
        suite, _ = parse_markdown(md)
        for step in suite.test_cases[0].steps:
            assert step.line_number > 0


# ═══════════════════════════════════════════════════════════════════════════
# File path attachment
# ═══════════════════════════════════════════════════════════════════════════


class TestFilePath:
    def test_file_path_attached_to_suite(self):
        suite, _ = parse_markdown("# S\n", file_path="/tests/login.md")
        assert suite.file_path == Path("/tests/login.md")

    def test_step_includes_file_path(self):
        md = "# S\n\n## T\n\n- Do something custom\n"
        suite, errors = parse_markdown(md, file_path="test.md")
        assert len(errors) == 0
        assert suite.test_cases[0].steps[0].file_path == Path("test.md")


# ═══════════════════════════════════════════════════════════════════════════
# Error reporting
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorReporting:
    def test_custom_step_produces_no_warning(self):
        md = '# S\n\n## T\n\n- Some unrecognised action\n'
        suite, errors = parse_markdown(md)
        assert len(errors) == 0
        # The step is still added to the scenario (as CUSTOM)
        assert suite.test_cases[0].steps[0].action_type == ActionType.CUSTOM

    def test_valid_steps_no_errors(self):
        md = '# S\n\n## T\n\n- Click "A"\n- Navigate to "https://x.com"\n'
        _, errors = parse_markdown(md)
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: realistic fixture file
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    FIXTURES_DIR = Path(__file__).parent / "fixtures"

    def test_login_fixture(self):
        suite, errors = parse_markdown_file(self.FIXTURES_DIR / "login_test.md")

        # Suite metadata
        assert suite.name == "Login Test Suite"
        assert "smoke" in suite.tags
        assert "regression" in suite.tags
        assert suite.file_path is not None

        # Suite-level setup
        assert suite.suite_setup_code is not None
        assert "BASE_URL" in suite.suite_setup_code

        # Test cases
        assert len(suite.test_cases) >= 3

        # First scenario: Successful Login
        tc1 = suite.test_cases[0]
        assert "Successful Login" in tc1.name
        assert "happy-path" in tc1.tags
        assert tc1.description is not None
        assert len(tc1.steps) == 6
        # Check variable extraction
        assert any("admin_email" in s.variables for s in tc1.steps)

        # Second scenario: Failed Login
        tc2 = suite.test_cases[1]
        assert "Failed Login" in tc2.name
        assert tc2.teardown_code is not None

        # Third scenario: Parameterised
        tc3 = suite.test_cases[2]
        assert len(tc3.parameters) == 2
        assert tc3.parameters[0]["username"] == "admin@test.com"
        assert tc3.parameters[1]["expected_page"] == "/editor"

    def test_simple_fixture(self):
        suite, errors = parse_markdown_file(self.FIXTURES_DIR / "simple_test.md")

        assert suite.name == "Simple Actions Test"
        assert len(suite.test_cases) >= 5

        # Verify CUSTOM steps detected
        custom_case = [tc for tc in suite.test_cases if "Custom" in tc.name or "Unrecognised" in tc.name]
        assert len(custom_case) >= 1
        for step in custom_case[0].steps:
            assert step.action_type == ActionType.CUSTOM

        # Verify no crashes — errors are all CUSTOM warnings
        for e in errors:
            assert "CUSTOM" in e.message
