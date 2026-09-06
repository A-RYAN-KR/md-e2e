"""Regression tests for EXECUTOR-003: Teardown failures being swallowed."""

import pytest
from md_e2e.models import TestSuite, TestCase, TestStep, ActionType, TargetType
from md_e2e.executor import execute_suite, StepStatus
from md_e2e.browser import BrowserConfig

@pytest.mark.asyncio
async def test_teardown_swallowed_scenario_success_teardown_fail(test_server):
    """TEST 1: Successful scenario + failing teardown -> FAILED"""
    test_case = TestCase(
        name="Test 1",
        line_number=1,
        steps=[
            TestStep(
                line_number=1,
                raw_text="Wait 10",
                action_type=ActionType.WAIT,
                target_type=TargetType.GENERIC,
                target_identifier="",
                value="10"
            )
        ],
        teardown_code="assert False, 'Deliberate scenario teardown failure'"
    )
    suite = TestSuite(name="Suite 1", test_cases=[test_case])
    config = BrowserConfig(headless=True)
    
    suite_result = await execute_suite(suite, config)
    scenario_result = suite_result.scenario_results[0]
    
    # Teardown failure should mark scenario as FAILED
    assert scenario_result.status == StepStatus.FAILED
    assert scenario_result.error is not None
    assert "Deliberate scenario teardown failure" in scenario_result.error


@pytest.mark.asyncio
async def test_teardown_swallowed_scenario_fail_teardown_fail(test_server):
    """TEST 2: Failing step + failing teardown -> remains FAILED (preserves original error)"""
    test_case = TestCase(
        name="Test 2",
        line_number=1,
        steps=[
            TestStep(
                line_number=1,
                raw_text="Click missing element",
                action_type=ActionType.CLICK,
                target_type=TargetType.BUTTON,
                target_identifier="Nonexistent Button",
                value=""
            )
        ],
        teardown_code="assert False, 'Deliberate scenario teardown failure'"
    )
    suite = TestSuite(name="Suite 2", test_cases=[test_case])
    config = BrowserConfig(headless=True, timeout=1000)
    
    suite_result = await execute_suite(suite, config)
    scenario_result = suite_result.scenario_results[0]
    
    # Scenario should be FAILED
    assert scenario_result.status == StepStatus.FAILED
    # Original step failure should be preserved, not overwritten by teardown error
    assert scenario_result.error is not None
    assert "TimeoutError" in scenario_result.error
    assert "Deliberate scenario teardown failure" not in scenario_result.error


@pytest.mark.asyncio
async def test_teardown_swallowed_scenario_success_teardown_success(test_server):
    """TEST 3: Successful scenario + successful teardown -> PASSED"""
    test_case = TestCase(
        name="Test 3",
        line_number=1,
        steps=[
            TestStep(
                line_number=1,
                raw_text="Wait 10",
                action_type=ActionType.WAIT,
                target_type=TargetType.GENERIC,
                target_identifier="",
                value="10"
            )
        ],
        teardown_code="x = 1 + 1"
    )
    suite = TestSuite(name="Suite 3", test_cases=[test_case])
    config = BrowserConfig(headless=True)
    
    suite_result = await execute_suite(suite, config)
    scenario_result = suite_result.scenario_results[0]
    
    assert scenario_result.status == StepStatus.PASSED


@pytest.mark.asyncio
async def test_teardown_swallowed_suite_success_teardown_fail(test_server):
    """TEST 4: Successful suite + failing suite teardown -> Suite FAILED"""
    test_case = TestCase(
        name="Test 4",
        line_number=1,
        steps=[
            TestStep(
                line_number=1,
                raw_text="Wait 10",
                action_type=ActionType.WAIT,
                target_type=TargetType.GENERIC,
                target_identifier="",
                value="10"
            )
        ]
    )
    suite = TestSuite(
        name="Suite 4",
        test_cases=[test_case],
        suite_teardown_code="assert False, 'Deliberate suite teardown failure'"
    )
    config = BrowserConfig(headless=True)
    
    suite_result = await execute_suite(suite, config)
    
    # Suite teardown failure should mark suite as FAILED
    assert suite_result.status == StepStatus.FAILED
    assert suite_result.error is not None
    assert "Deliberate suite teardown failure" in suite_result.error
