"""Unit tests for md_e2e.models — IR data model construction and defaults."""

import pytest
from pathlib import Path

from md_e2e.models import (
    ActionType,
    TargetType,
    TestStep,
    TestCase,
    TestSuite,
    ParseError,
)


# ── StrEnum behaviour ────────────────────────────────────────────────────────


class TestActionTypeEnum:
    def test_string_comparison(self):
        assert ActionType.CLICK == "CLICK"

    def test_membership(self):
        assert "NAVIGATE" in ActionType.__members__
        assert "CUSTOM" in ActionType.__members__

    def test_custom_is_defined(self):
        """CUSTOM must exist as the fallback for unrecognised steps."""
        assert ActionType.CUSTOM == "CUSTOM"

    def test_all_expected_members_exist(self):
        expected = {
            "NAVIGATE", "RELOAD", "CLICK", "FILL", "SELECT", "HOVER",
            "PRESS", "UPLOAD", "CHECK", "UNCHECK",
            "ASSERT_VISIBLE", "ASSERT_HIDDEN", "ASSERT_URL",
            "ASSERT_TITLE", "ASSERT_VALUE", "ASSERT_COUNT",
            "ASSERT_VARIABLE", "WAIT", "STORE_VARIABLE", "CUSTOM",
        }
        assert set(ActionType.__members__.keys()) == expected


class TestTargetTypeEnum:
    def test_string_comparison(self):
        assert TargetType.BUTTON == "BUTTON"

    def test_generic_is_default_sentinel(self):
        assert TargetType.GENERIC == "GENERIC"

    def test_all_expected_members_exist(self):
        expected = {
            "BUTTON", "LINK", "INPUT", "HEADING", "TEXT",
            "CHECKBOX", "RADIO", "GENERIC",
        }
        assert set(TargetType.__members__.keys()) == expected


# ── TestStep defaults ────────────────────────────────────────────────────────


class TestStepDataclass:
    def test_minimal_construction(self):
        step = TestStep(
            raw_text="Click 'Submit'",
            line_number=10,
            action_type=ActionType.CLICK,
        )
        assert step.raw_text == "Click 'Submit'"
        assert step.line_number == 10
        assert step.action_type == ActionType.CLICK
        assert step.target_type == TargetType.GENERIC
        assert step.target_identifier is None
        assert step.value is None
        assert step.is_checklist_item is False
        assert step.is_checked is False
        assert step.variables == []

    def test_full_construction(self):
        step = TestStep(
            raw_text='Fill "Email" with "{{user}}"',
            line_number=5,
            action_type=ActionType.FILL,
            target_type=TargetType.INPUT,
            target_identifier="Email",
            value="{{user}}",
            is_checklist_item=True,
            is_checked=True,
            variables=["user"],
        )
        assert step.target_type == TargetType.INPUT
        assert step.target_identifier == "Email"
        assert step.value == "{{user}}"
        assert step.is_checklist_item is True
        assert step.is_checked is True
        assert step.variables == ["user"]

    def test_variables_default_empty_list(self):
        s1 = TestStep(raw_text="a", line_number=1, action_type=ActionType.CLICK)
        s2 = TestStep(raw_text="b", line_number=2, action_type=ActionType.CLICK)
        # Ensure independent default lists (no shared mutable default)
        s1.variables.append("x")
        assert s2.variables == []


# ── TestCase defaults ────────────────────────────────────────────────────────


class TestCaseDataclass:
    def test_minimal_construction(self):
        tc = TestCase(name="Login", line_number=3)
        assert tc.name == "Login"
        assert tc.steps == []
        assert tc.description is None
        assert tc.parameters == []
        assert tc.setup_code is None
        assert tc.teardown_code is None
        assert tc.tags == []

    def test_with_steps_and_parameters(self):
        step = TestStep(raw_text="x", line_number=1, action_type=ActionType.CLICK)
        tc = TestCase(
            name="Data-driven",
            line_number=5,
            steps=[step],
            parameters=[{"user": "alice"}, {"user": "bob"}],
            tags=["smoke"],
        )
        assert len(tc.steps) == 1
        assert len(tc.parameters) == 2
        assert tc.tags == ["smoke"]


# ── TestSuite defaults ───────────────────────────────────────────────────────


class TestSuiteDataclass:
    def test_minimal_construction(self):
        ts = TestSuite(name="My Suite")
        assert ts.name == "My Suite"
        assert ts.file_path is None
        assert ts.description is None
        assert ts.tags == []
        assert ts.suite_setup_code is None
        assert ts.suite_teardown_code is None
        assert ts.test_cases == []

    def test_with_file_path(self):
        ts = TestSuite(name="S", file_path=Path("tests/login.md"))
        assert ts.file_path == Path("tests/login.md")


# ── ParseError ───────────────────────────────────────────────────────────────


class TestParseErrorDataclass:
    def test_construction(self):
        e = ParseError(
            file_path=Path("test.md"),
            line_number=42,
            message="Unrecognised step",
            raw_text="Do magic",
        )
        assert e.file_path == Path("test.md")
        assert e.line_number == 42
        assert e.message == "Unrecognised step"
        assert e.raw_text == "Do magic"

    def test_optional_fields(self):
        e = ParseError(file_path=None, line_number=1, message="oops")
        assert e.file_path is None
        assert e.raw_text is None
