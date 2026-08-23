"""IR data models for the md-e2e test runner.

Defines the Intermediate Representation (IR) schema used to represent
parsed Markdown test specifications as structured, executable data.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ActionType(StrEnum):
    """Enumeration of all recognised DSL action types.

    Every step parsed from a Markdown bullet is tagged with one of these.
    ``CUSTOM`` is the fallback for steps that do not match the built-in
    grammar — Phase 3's ``@step(...)`` registry can resolve them at runtime.
    """

    # Navigation
    NAVIGATE = "NAVIGATE"
    RELOAD = "RELOAD"

    # Interaction
    CLICK = "CLICK"
    FILL = "FILL"
    SELECT = "SELECT"
    HOVER = "HOVER"
    PRESS = "PRESS"
    UPLOAD = "UPLOAD"
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"

    # Assertions
    ASSERT_VISIBLE = "ASSERT_VISIBLE"
    ASSERT_HIDDEN = "ASSERT_HIDDEN"
    ASSERT_URL = "ASSERT_URL"
    ASSERT_TITLE = "ASSERT_TITLE"
    ASSERT_VALUE = "ASSERT_VALUE"
    ASSERT_COUNT = "ASSERT_COUNT"
    ASSERT_VARIABLE = "ASSERT_VARIABLE"

    # State & Control
    WAIT = "WAIT"
    WAIT_URL = "WAIT_URL"
    STORE_VARIABLE = "STORE_VARIABLE"

    # Fallback for custom / unrecognised steps
    CUSTOM = "CUSTOM"


class TargetType(StrEnum):
    """Semantic role of the UI element targeted by an action."""

    BUTTON = "BUTTON"
    LINK = "LINK"
    INPUT = "INPUT"
    HEADING = "HEADING"
    TEXT = "TEXT"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    TESTID = "TESTID"
    GENERIC = "GENERIC"


@dataclass
class TestStep:
    """A single executable step parsed from a Markdown list item.

    Field conventions for assertion steps:
        ASSERT_VISIBLE / ASSERT_HIDDEN:
            target_type  – element role (HEADING, BUTTON, …) or GENERIC
            target_identifier – the text / label to locate
        ASSERT_URL / ASSERT_TITLE:
            target_identifier – comparison mode ("is", "contains", "matches")
            value – expected URL or title string
        ASSERT_VALUE:
            target_identifier – field name
            value – ``"<cmp>:<expected>"`` e.g. ``"is:hello@example.com"``
                    (split on the *first* colon to recover comparison mode)
    """

    __test__ = False

    raw_text: str
    line_number: int
    action_type: ActionType
    target_type: TargetType = TargetType.GENERIC
    target_identifier: str | None = None
    value: str | None = None
    is_checklist_item: bool = False
    is_checked: bool = False
    variables: list[str] = field(default_factory=list)


@dataclass
class TestCase:
    """A single test scenario parsed from a ``## Heading``."""

    __test__ = False

    name: str
    line_number: int
    steps: list[TestStep] = field(default_factory=list)
    description: str | None = None
    parameters: list[dict[str, str]] = field(default_factory=list)
    setup_code: str | None = None
    teardown_code: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class TestSuite:
    """Top-level container representing an entire Markdown test file.

    ``suite_setup_code`` / ``suite_teardown_code`` are extracted from
    fenced code blocks that appear **before** the first ``## Scenario``.
    """

    __test__ = False

    name: str
    file_path: Path | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    suite_setup_code: str | None = None
    suite_teardown_code: str | None = None
    test_cases: list[TestCase] = field(default_factory=list)


@dataclass
class ParseError:
    """Structured error emitted when a line cannot be parsed."""

    file_path: Path | None
    line_number: int
    message: str
    raw_text: str | None = None


@dataclass
class HealingEvent:
    """Record of a self-healing resolution event during step execution."""

    file_path: Path | None
    line_number: int
    original_text: str
    healed_text: str
    original_identifier: str
    healed_identifier: str
    strategy_used: str  # "cache", "fuzzy_heuristic", "llm"

