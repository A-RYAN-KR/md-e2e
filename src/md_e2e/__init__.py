"""md-e2e — Zero-Glue-Code, Markdown-Based E2E Test Runner.

Public API re-exports for convenience::

    from md_e2e import parse_markdown, parse_markdown_file, parse_step
    from md_e2e import TestSuite, TestCase, TestStep, ParseError
    from md_e2e import ActionType, TargetType
"""

from .browser import BrowserConfig, BrowserSession
from .custom_steps import clear_custom_steps, custom_step
from .dsl_parser import parse_step
from .executor import (
    ScenarioResult,
    StepResult,
    StepStatus,
    SuiteResult,
    execute_scenario,
    execute_step,
    execute_suite,
)
from .healing import HealingCache, generate_healing_diff, set_llm_handler
from .md_parser import parse_markdown, parse_markdown_file
from .models import (
    ActionType,
    HealingEvent,
    ParseError,
    TargetType,
    TestCase,
    TestStep,
    TestSuite,
)
from .variables import UndefinedVariableError, VariableStore

__version__ = "0.4.0"

__all__ = [
    "__version__",
    "ActionType",
    "BrowserConfig",
    "BrowserSession",
    "HealingCache",
    "HealingEvent",
    "ParseError",
    "ScenarioResult",
    "StepResult",
    "StepStatus",
    "SuiteResult",
    "TargetType",
    "TestCase",
    "TestStep",
    "TestSuite",
    "UndefinedVariableError",
    "VariableStore",
    "clear_custom_steps",
    "custom_step",
    "execute_scenario",
    "execute_step",
    "execute_suite",
    "generate_healing_diff",
    "parse_markdown",
    "parse_markdown_file",
    "parse_step",
    "set_llm_handler",
]

