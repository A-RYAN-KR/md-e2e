"""Integration tests for the step and suite execution engines."""

import re
import shutil
import tempfile
from pathlib import Path
import pytest

from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.executor import (
    execute_step,
    execute_scenario,
    execute_suite,
    StepStatus,
    StepNotImplementedError,
)
from md_e2e.models import ActionType, TargetType, TestStep, TestCase, TestSuite
from md_e2e.variables import VariableStore, UndefinedVariableError


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


@pytest.mark.asyncio
async def test_execute_step_actions(test_server):
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            await page.goto(f"{test_server}/test_app.html")
            
            store = VariableStore()
            
            # Test NAVIGATE
            step_nav = TestStep(
                raw_text="Navigate", line_number=1, action_type=ActionType.NAVIGATE,
                target_identifier=f"{test_server}/test_app.html"
            )
            res = await execute_step(step_nav, page, store)
            assert res.status == StepStatus.PASSED
            
            # Test FILL
            step_fill = TestStep(
                raw_text="Fill email", line_number=2, action_type=ActionType.FILL,
                target_type=TargetType.INPUT, target_identifier="Email", value="test@user.com"
            )
            res = await execute_step(step_fill, page, store)
            assert res.status == StepStatus.PASSED
            assert await page.locator("#email-input").input_value() == "test@user.com"
            
            # Test ASSERT_VALUE
            step_val = TestStep(
                raw_text="Assert email value", line_number=3, action_type=ActionType.ASSERT_VALUE,
                target_type=TargetType.INPUT, target_identifier="Email", value="is:test@user.com"
            )
            res = await execute_step(step_val, page, store)
            assert res.status == StepStatus.PASSED
            
            # Test CHECK/UNCHECK
            step_chk = TestStep(
                raw_text="Check newsletter", line_number=4, action_type=ActionType.CHECK,
                target_type=TargetType.CHECKBOX, target_identifier="Remember me"
            )
            res = await execute_step(step_chk, page, store)
            assert res.status == StepStatus.PASSED
            assert await page.locator("#remember-me-checkbox").is_checked() is True
            
            # Test STORE_VARIABLE
            step_store = TestStep(
                raw_text="Store price", line_number=5, action_type=ActionType.STORE_VARIABLE,
                target_identifier="#price-value", value="PRICE"
            )
            res = await execute_step(step_store, page, store)
            assert res.status == StepStatus.PASSED
            assert store.get("PRICE") == "$42.00"
            
            # Test SELECT option
            step_sel = TestStep(
                raw_text="Select option", line_number=6, action_type=ActionType.SELECT,
                target_identifier="Dropdown", value="Option B"
            )
            res = await execute_step(step_sel, page, store)
            assert res.status == StepStatus.PASSED
            assert await page.locator("#dropdown-select").input_value() == "B"
            
            # Test HOVER
            step_hover = TestStep(
                raw_text="Hover Help", line_number=7, action_type=ActionType.HOVER,
                target_identifier="Hover over me"
            )
            res = await execute_step(step_hover, page, store)
            assert res.status == StepStatus.PASSED
            assert await page.locator("#hover-text").is_visible() is True
            
            # Test ASSERT_VISIBLE / ASSERT_HIDDEN
            step_vis = TestStep(
                raw_text="Assert visible", line_number=8, action_type=ActionType.ASSERT_VISIBLE,
                target_identifier="Help text visible!"
            )
            res = await execute_step(step_vis, page, store)
            assert res.status == StepStatus.PASSED
            
            # Test WAIT network idle (should pass quickly on local server)
            step_wait = TestStep(
                raw_text="Wait network", line_number=9, action_type=ActionType.WAIT,
                value="network_idle"
            )
            res = await execute_step(step_wait, page, store)
            assert res.status == StepStatus.PASSED


@pytest.mark.asyncio
async def test_execute_scenario_basic(test_server, tmp_dir):
    config = BrowserConfig(headless=True, screenshot_dir=tmp_dir)
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            store = VariableStore()
            
            steps = [
                TestStep(raw_text="Nav", line_number=1, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
                TestStep(raw_text="Fill", line_number=2, action_type=ActionType.FILL, target_identifier="Email", value="abc@def.com"),
                TestStep(raw_text="Assert val", line_number=3, action_type=ActionType.ASSERT_VALUE, target_identifier="Email", value="contains:abc"),
            ]
            
            # Test success scenario
            tc = TestCase(name="Successful Test", line_number=10, steps=steps)
            results = await execute_scenario(tc, page, store, config)
            assert len(results) == 1
            assert results[0].status == StepStatus.PASSED
            assert len(results[0].step_results) == 3
            assert results[0].step_results[0].status == StepStatus.PASSED
            
            # Test failure scenario (with failure screenshot)
            tc_fail = TestCase(name="Failing Test", line_number=20, steps=[
                TestStep(raw_text="Nav", line_number=21, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
                TestStep(raw_text="Assert non-existing heading", line_number=22, action_type=ActionType.ASSERT_VISIBLE, target_type=TargetType.HEADING, target_identifier="Does Not Exist")
            ])
            # Set short timeout to avoid waiting 30 seconds for non-existing element
            context.set_default_timeout(1000)
            results_fail = await execute_scenario(tc_fail, page, store, config)
            assert results_fail[0].status == StepStatus.FAILED
            assert results_fail[0].step_results[1].status == StepStatus.FAILED
            assert results_fail[0].step_results[1].screenshot_path is not None
            assert results_fail[0].step_results[1].screenshot_path.exists()


@pytest.mark.asyncio
async def test_execute_scenario_parameterised(test_server):
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            store = VariableStore()
            
            steps = [
                TestStep(raw_text="Nav", line_number=1, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
                TestStep(raw_text="Fill", line_number=2, action_type=ActionType.FILL, target_identifier="Email", value="{{username}}"),
                TestStep(raw_text="Assert val", line_number=3, action_type=ActionType.ASSERT_VALUE, target_identifier="Email", value="is:{{username}}"),
            ]
            
            parameters = [
                {"username": "userA@test.com"},
                {"username": "userB@test.com"},
            ]
            
            tc = TestCase(name="Param Login", line_number=10, steps=steps, parameters=parameters)
            results = await execute_scenario(tc, page, store, config)
            assert len(results) == 2
            assert results[0].name == "Param Login [row 1: username=userA@test.com]"
            assert results[0].status == StepStatus.PASSED
            assert results[1].name == "Param Login [row 2: username=userB@test.com]"
            assert results[1].status == StepStatus.PASSED


@pytest.mark.asyncio
async def test_execute_scenario_hooks(test_server):
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            store = VariableStore()
            
            setup_code = "config.locale = 'setup_ran'"
            teardown_code = "config.locale = 'teardown_ran'"
            
            steps = [
                TestStep(raw_text="Nav", line_number=1, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
            ]
            
            tc = TestCase(
                name="Hooks Scenario",
                line_number=10,
                steps=steps,
                setup_code=setup_code,
                teardown_code=teardown_code
            )
            
            results = await execute_scenario(tc, page, store, config)
            assert results[0].status == StepStatus.PASSED
            assert config.locale == "teardown_ran"


@pytest.mark.asyncio
async def test_execute_suite_flow(test_server, tmp_dir):
    # Set trace_dir to capture failure traces
    config = BrowserConfig(headless=True, trace_dir=tmp_dir)
    
    tc1 = TestCase(name="First Test", line_number=10, steps=[
        TestStep(raw_text="Nav", line_number=11, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
    ])
    tc2 = TestCase(name="Second Test", line_number=20, steps=[
        TestStep(raw_text="Nav", line_number=21, action_type=ActionType.NAVIGATE, target_identifier=f"{test_server}/test_app.html"),
        TestStep(raw_text="Fail here", line_number=22, action_type=ActionType.ASSERT_VISIBLE, target_identifier="NonExistingElement")
    ])
    
    suite = TestSuite(
        name="My Test Suite",
        suite_setup_code="store.store('SUITE_SETUP', 'ran')",
        suite_teardown_code="store.store('SUITE_TEARDOWN', 'ran')",
        test_cases=[tc1, tc2]
    )
    
    # Run the suite. Note we configure a short timeout for the tracing failure test so it fails fast
    config.timeout = 500
    res = await execute_suite(suite, config)
    
    assert res.name == "My Test Suite"
    assert res.total == 2
    assert res.passed == 1
    assert res.failed == 1
    assert res.status == StepStatus.FAILED
    
    # Validate trace path was captured for the failing scenario
    failed_sc = [s for s in res.scenario_results if s.status == StepStatus.FAILED][0]
    assert failed_sc.trace_path is not None
    assert failed_sc.trace_path.exists()
