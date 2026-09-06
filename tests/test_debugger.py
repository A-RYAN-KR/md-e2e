import pytest
import asyncio
import builtins
from pathlib import Path

from md_e2e.models import TestCase, TestStep, ActionType, TargetType, TestSuite
from md_e2e.executor import execute_suite
from md_e2e.browser import BrowserConfig

@pytest.mark.asyncio
async def test_debugger_retry_execution(test_server):
    """
    Verify that the 'r' (retry) command actually executes the step and doesn't just infinitely prompt,
    and that 's' (skip) behaves correctly after it.
    """
    # A step that does something observable (store a variable)
    step1 = TestStep(
        line_number=1,
        raw_text="Store variable",
        action_type=ActionType.CUSTOM,
        target_type=TargetType.GENERIC,
        target_identifier="",
        value=""
    )
    # A second step just to ensure we advance properly
    step2 = TestStep(
        line_number=2,
        raw_text="Wait 0",
        action_type=ActionType.WAIT,
        target_type=TargetType.GENERIC,
        target_identifier="",
        value="0"
    )
    
    test_case = TestCase(name="Debugger Retry Test", line_number=1, steps=[step1, step2])
    suite = TestSuite(name="Debugger Suite", test_cases=[test_case])
    config = BrowserConfig(headless=True)
    
    # We will mock the custom handler to increment a counter
    counter = {"val": 0}
    async def custom_handler(page, store):
        counter["val"] += 1
    
    # Mock inputs:
    # 1st prompt (step 1): 'r' -> execute step 1, advance_after=False
    # 2nd prompt (step 1): 's' -> skip step 1, advance_after=True
    # 3rd prompt (step 2): '' (Enter) -> execute step 2, advance_after=True
    inputs = ['r', 's', '']
    original_input = builtins.input
    def mock_input(prompt):
        return inputs.pop(0)
    
    builtins.input = mock_input
    
    from md_e2e.custom_steps import _custom_steps_registry, CustomStepEntry
    import re
    entry = CustomStepEntry(pattern=re.compile("Store variable"), handler=custom_handler, source_dir=Path("."))
    _custom_steps_registry.append(entry)
    
    try:
        result = await execute_suite(suite, config, step_debug=True)
    finally:
        builtins.input = original_input
        _custom_steps_registry.remove(entry)
        
    assert counter["val"] == 1, "The step should have executed exactly once during the 'r' command"
    
    scen_result = result.scenario_results[0]
    
    # 'r' -> execute_step returns PASSED
    # 's' -> appends SKIPPED
    # 'Wait 0' -> execute_step returns PASSED
    assert len(scen_result.step_results) == 3
    assert scen_result.step_results[0].status.value == "PASSED"
    assert scen_result.step_results[1].status.value == "SKIPPED"
    assert scen_result.step_results[2].status.value == "PASSED"

@pytest.mark.asyncio
async def test_debugger_next_and_edit_execution(test_server):
    """
    Verify that existing commands (next, edit) still behave correctly.
    """
    step1 = TestStep(
        line_number=1,
        raw_text="Wait 0",
        action_type=ActionType.WAIT,
        target_type=TargetType.GENERIC,
        target_identifier="",
        value="0"
    )
    
    test_case = TestCase(name="Debugger Next Test", line_number=1, steps=[step1])
    suite = TestSuite(name="Debugger Suite", test_cases=[test_case])
    config = BrowserConfig(headless=True)
    
    # Inputs:
    # 'e' -> edit step
    # 'Wait 10' -> new text
    # '' -> execute
    inputs = ['e', 'Wait 10', '']
    original_input = builtins.input
    def mock_input(prompt):
        return inputs.pop(0)
    builtins.input = mock_input
    
    try:
        result = await execute_suite(suite, config, step_debug=True)
    finally:
        builtins.input = original_input
        
    scen_result = result.scenario_results[0]
    assert len(scen_result.step_results) == 1
    assert scen_result.step_results[0].step.raw_text == "Wait 10"
