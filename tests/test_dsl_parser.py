"""Unit tests for md_e2e.dsl_parser — DSL grammar coverage.

Each grammar rule has at least two test cases (happy-path + edge-case/variant).
Tests also cover:
- Flexible quoting (double, single, backtick)
- Case-insensitive keywords
- Variable extraction (Jinja-style and shell-style)
- Graceful CUSTOM fallback for unrecognised steps
"""

import pytest

from md_e2e.dsl_parser import parse_step, _extract_variables
from md_e2e.models import ActionType, TargetType


# ═══════════════════════════════════════════════════════════════════════════
# Navigation
# ═══════════════════════════════════════════════════════════════════════════


class TestNavigate:
    def test_navigate_to_url(self):
        step, err = parse_step('Navigate to "https://example.com"')
        assert err is None
        assert step.action_type == ActionType.NAVIGATE
        assert step.target_identifier == "https://example.com"

    def test_go_to_url(self):
        step, err = parse_step("Go to 'https://example.com/login'")
        assert err is None
        assert step.action_type == ActionType.NAVIGATE
        assert step.target_identifier == "https://example.com/login"

    def test_case_insensitive(self):
        step, err = parse_step('NAVIGATE TO "https://x.com"')
        assert err is None
        assert step.action_type == ActionType.NAVIGATE

    def test_backtick_quoted_url(self):
        step, err = parse_step("Navigate to `https://example.com`")
        assert err is None
        assert step.target_identifier == "https://example.com"


class TestReload:
    def test_reload(self):
        step, err = parse_step("Reload")
        assert err is None
        assert step.action_type == ActionType.RELOAD

    def test_reload_page(self):
        step, err = parse_step("Reload page")
        assert err is None
        assert step.action_type == ActionType.RELOAD

    def test_case_insensitive(self):
        step, err = parse_step("RELOAD PAGE")
        assert err is None
        assert step.action_type == ActionType.RELOAD


# ═══════════════════════════════════════════════════════════════════════════
# Interaction
# ═══════════════════════════════════════════════════════════════════════════


class TestClick:
    def test_click_bare(self):
        step, err = parse_step('Click "Submit"')
        assert err is None
        assert step.action_type == ActionType.CLICK
        assert step.target_identifier == "Submit"
        assert step.target_type == TargetType.GENERIC

    def test_click_button(self):
        step, err = parse_step('Click button "Save"')
        assert err is None
        assert step.target_type == TargetType.BUTTON
        assert step.target_identifier == "Save"

    def test_click_link(self):
        step, err = parse_step("Click link 'Home'")
        assert err is None
        assert step.target_type == TargetType.LINK
        assert step.target_identifier == "Home"

    def test_click_checkbox(self):
        step, err = parse_step('Click checkbox "Terms"')
        assert err is None
        assert step.target_type == TargetType.CHECKBOX

    def test_click_css_selector(self):
        step, err = parse_step('Click "#submit-btn"')
        assert err is None
        assert step.target_identifier == "#submit-btn"


class TestFill:
    def test_fill_basic(self):
        step, err = parse_step('Fill "Email" with "user@example.com"')
        assert err is None
        assert step.action_type == ActionType.FILL
        assert step.target_identifier == "Email"
        assert step.value == "user@example.com"

    def test_fill_with_target_type(self):
        step, err = parse_step('Fill input "username" with "admin"')
        assert err is None
        assert step.target_type == TargetType.INPUT
        assert step.target_identifier == "username"
        assert step.value == "admin"

    def test_fill_with_variable(self):
        step, err = parse_step('Fill "Password" with "{{secret}}"')
        assert err is None
        assert step.value == "{{secret}}"
        assert "secret" in step.variables

    def test_fill_mixed_quotes(self):
        step, err = parse_step("Fill 'Search' with `test query`")
        assert err is None
        assert step.target_identifier == "Search"
        assert step.value == "test query"


class TestSelect:
    def test_select_from(self):
        step, err = parse_step('Select "Option A" from "Dropdown"')
        assert err is None
        assert step.action_type == ActionType.SELECT
        assert step.value == "Option A"
        assert step.target_identifier == "Dropdown"

    def test_select_case_insensitive(self):
        step, err = parse_step('SELECT "Red" FROM "Color Picker"')
        assert err is None
        assert step.action_type == ActionType.SELECT


class TestHover:
    def test_hover_bare(self):
        step, err = parse_step('Hover "Profile Menu"')
        assert err is None
        assert step.action_type == ActionType.HOVER
        assert step.target_identifier == "Profile Menu"

    def test_hover_over(self):
        step, err = parse_step('Hover over "Settings"')
        assert err is None
        assert step.action_type == ActionType.HOVER
        assert step.target_identifier == "Settings"

    def test_hover_with_type(self):
        step, err = parse_step('Hover button "Help"')
        assert err is None
        assert step.target_type == TargetType.BUTTON


class TestPress:
    def test_press_key(self):
        step, err = parse_step('Press "Enter"')
        assert err is None
        assert step.action_type == ActionType.PRESS
        assert step.target_identifier == "Enter"

    def test_press_combo(self):
        step, err = parse_step('Press "Control+Shift+K"')
        assert err is None
        assert step.target_identifier == "Control+Shift+K"


class TestUpload:
    def test_upload_file(self):
        step, err = parse_step('Upload "report.pdf" to "File Input"')
        assert err is None
        assert step.action_type == ActionType.UPLOAD
        assert step.value == "report.pdf"
        assert step.target_identifier == "File Input"


class TestCheck:
    def test_check(self):
        step, err = parse_step('Check "Remember me"')
        assert err is None
        assert step.action_type == ActionType.CHECK
        assert step.target_identifier == "Remember me"

    def test_check_checkbox(self):
        step, err = parse_step('Check checkbox "Terms"')
        assert err is None
        assert step.target_type == TargetType.CHECKBOX

    def test_uncheck(self):
        step, err = parse_step('Uncheck "Newsletter"')
        assert err is None
        assert step.action_type == ActionType.UNCHECK
        assert step.target_identifier == "Newsletter"

    def test_uncheck_with_type(self):
        step, err = parse_step('Uncheck checkbox "Auto-renew"')
        assert err is None
        assert step.action_type == ActionType.UNCHECK
        assert step.target_type == TargetType.CHECKBOX


# ═══════════════════════════════════════════════════════════════════════════
# Assertions
# ═══════════════════════════════════════════════════════════════════════════


class TestAssertVisibility:
    def test_assert_visible_bare(self):
        step, err = parse_step('Assert "Welcome" is visible')
        assert err is None
        assert step.action_type == ActionType.ASSERT_VISIBLE
        assert step.target_identifier == "Welcome"

    def test_assert_visible_heading(self):
        step, err = parse_step('Assert heading "Dashboard" is visible')
        assert err is None
        assert step.action_type == ActionType.ASSERT_VISIBLE
        assert step.target_type == TargetType.HEADING
        assert step.target_identifier == "Dashboard"

    def test_assert_hidden(self):
        step, err = parse_step('Assert button "Delete" is hidden')
        assert err is None
        assert step.action_type == ActionType.ASSERT_HIDDEN
        assert step.target_type == TargetType.BUTTON
        assert step.target_identifier == "Delete"

    def test_assert_hidden_bare(self):
        step, err = parse_step('Assert "Spinner" is hidden')
        assert err is None
        assert step.action_type == ActionType.ASSERT_HIDDEN


class TestAssertURL:
    def test_assert_url_is(self):
        step, err = parse_step('Assert URL is "https://example.com"')
        assert err is None
        assert step.action_type == ActionType.ASSERT_URL
        assert step.target_identifier == "is"
        assert step.value == "https://example.com"

    def test_assert_url_contains(self):
        step, err = parse_step('Assert URL contains "/dashboard"')
        assert err is None
        assert step.action_type == ActionType.ASSERT_URL
        assert step.target_identifier == "contains"
        assert step.value == "/dashboard"

    def test_assert_url_matches(self):
        step, err = parse_step(r'Assert URL matches "/users/\d+"')
        assert err is None
        assert step.target_identifier == "matches"


class TestAssertTitle:
    def test_assert_title_is(self):
        step, err = parse_step('Assert title is "My App"')
        assert err is None
        assert step.action_type == ActionType.ASSERT_TITLE
        assert step.target_identifier == "is"
        assert step.value == "My App"

    def test_assert_title_contains(self):
        step, err = parse_step('Assert title contains "App"')
        assert err is None
        assert step.target_identifier == "contains"
        assert step.value == "App"


class TestAssertValue:
    def test_assert_value_is(self):
        step, err = parse_step('Assert "email" value is "test@example.com"')
        assert err is None
        assert step.action_type == ActionType.ASSERT_VALUE
        assert step.target_identifier == "email"
        assert step.value == "is:test@example.com"

    def test_assert_value_contains(self):
        step, err = parse_step('Assert "email" value contains "test"')
        assert err is None
        assert step.target_identifier == "email"
        assert step.value == "contains:test"


# ═══════════════════════════════════════════════════════════════════════════
# State & Control
# ═══════════════════════════════════════════════════════════════════════════


class TestWait:
    def test_wait_seconds(self):
        step, err = parse_step("Wait 3 seconds")
        assert err is None
        assert step.action_type == ActionType.WAIT
        assert step.value == "3"

    def test_wait_singular(self):
        step, err = parse_step("Wait 1 second")
        assert err is None
        assert step.value == "1"

    def test_wait_network_idle(self):
        step, err = parse_step("Wait for network idle")
        assert err is None
        assert step.action_type == ActionType.WAIT
        assert step.value == "network_idle"


class TestStoreVariable:
    def test_store_with_type(self):
        step, err = parse_step('Store text from heading "Welcome" as "greeting"')
        assert err is None
        assert step.action_type == ActionType.STORE_VARIABLE
        assert step.target_type == TargetType.HEADING
        assert step.target_identifier == "Welcome"
        assert step.value == "greeting"

    def test_store_bare(self):
        step, err = parse_step('Store text from "Price" as "item_price"')
        assert err is None
        assert step.action_type == ActionType.STORE_VARIABLE
        assert step.target_identifier == "Price"
        assert step.value == "item_price"


# ═══════════════════════════════════════════════════════════════════════════
# Variable extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestVariableExtraction:
    def test_jinja_style(self):
        step, err = parse_step('Fill "Email" with "{{user_email}}"')
        assert "user_email" in step.variables

    def test_jinja_with_spaces(self):
        step, err = parse_step('Fill "Email" with "{{ user_email }}"')
        assert "user_email" in step.variables

    def test_shell_style(self):
        step, err = parse_step('Fill "Password" with "${PASSWORD}"')
        assert "PASSWORD" in step.variables

    def test_multiple_variables(self):
        step, err = parse_step('Fill "Query" with "{{first}} and ${second}"')
        assert step.variables == ["first", "second"]

    def test_deduplication(self):
        step, err = parse_step('Fill "X" with "{{a}} {{a}}"')
        assert step.variables == ["a"]

    def test_no_variables(self):
        step, err = parse_step('Click "Submit"')
        assert step.variables == []

    def test_extract_variables_standalone(self):
        assert _extract_variables("Hello {{world}}") == ["world"]
        assert _extract_variables("${A} and ${B}") == ["A", "B"]
        assert _extract_variables("no vars here") == []


# ═══════════════════════════════════════════════════════════════════════════
# CUSTOM fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestCustomFallback:
    def test_unrecognised_step_tagged_custom(self):
        step, err = parse_step("Do something completely custom")
        assert step.action_type == ActionType.CUSTOM
        assert err is not None
        assert "CUSTOM" in err.message

    def test_custom_preserves_raw_text(self):
        step, err = parse_step("Verify database has 5 records", line_number=42)
        assert step.action_type == ActionType.CUSTOM
        assert step.raw_text == "Verify database has 5 records"
        assert step.line_number == 42

    def test_custom_with_variables(self):
        step, err = parse_step("Send email to {{recipient}}")
        assert step.action_type == ActionType.CUSTOM
        assert "recipient" in step.variables


# ═══════════════════════════════════════════════════════════════════════════
# Line number passthrough
# ═══════════════════════════════════════════════════════════════════════════


class TestLineNumber:
    def test_line_number_passed_through(self):
        step, _ = parse_step('Click "OK"', line_number=99)
        assert step.line_number == 99

    def test_default_line_number(self):
        step, _ = parse_step('Click "OK"')
        assert step.line_number == 0
