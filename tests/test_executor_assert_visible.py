"""Regression test for EXECUTOR-001 (ASSERT_VISIBLE TargetType bypass)."""

import pytest
from playwright.async_api import async_playwright

from md_e2e.models import TestStep, ActionType, TargetType
from md_e2e.executor import _dispatch_action
from md_e2e.variables import VariableStore
from md_e2e.browser import BrowserConfig, BrowserSession

@pytest.mark.asyncio
async def test_bug_executor_001_assert_visible_fallback(test_server):
    """
    Test that ASSERT_VISIBLE respects TargetType and does not falsely pass
    by falling back to generic text matching when a specific semantic
    target is requested but missing.
    """
    config = BrowserConfig(headless=True, timeout=2000)
    store = VariableStore()
    
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            # Load a page with a paragraph and a hidden button, both containing "Accept Terms"
            # and a visible button "Submit".
            await page.set_content('''
                <html>
                    <body>
                        <p>Accept Terms</p>
                        <button style="display:none">Accept Terms</button>
                        <button>Submit</button>
                    </body>
                </html>
            ''')
            
            # CASE A: Assert button "Submit" is visible. Expected: PASS
            step_a = TestStep(
                line_number=1,
                raw_text='Assert button "Submit" is visible',
                action_type=ActionType.ASSERT_VISIBLE,
                target_type=TargetType.BUTTON,
                target_identifier="Submit",
                value=""
            )
            # Should not raise an exception
            await _dispatch_action(step_a, page, store, "Submit", "", config)
            
            # CASE B: Assert button "Accept Terms" is visible. Expected: FAIL
            step_b = TestStep(
                line_number=2,
                raw_text='Assert button "Accept Terms" is visible',
                action_type=ActionType.ASSERT_VISIBLE,
                target_type=TargetType.BUTTON,
                target_identifier="Accept Terms",
                value=""
            )
            # The requested button is hidden. The paragraph is visible.
            # The fallback must NOT convert this to a PASS. It should raise an exception.
            with pytest.raises(Exception):
                await _dispatch_action(step_b, page, store, "Accept Terms", "", config)
            
            # CASE C: Assert generic text "Accept Terms" is visible. Expected: PASS
            # This ensures we preserve the legitimate behavior of the fallback for GENERIC types.
            step_c = TestStep(
                line_number=3,
                raw_text='Assert "Accept Terms" is visible',
                action_type=ActionType.ASSERT_VISIBLE,
                target_type=TargetType.GENERIC,
                target_identifier="Accept Terms",
                value=""
            )
            # Should pass because the <p>Accept Terms</p> is visible, and GENERIC target
            # is allowed to use the text-container fallback.
            await _dispatch_action(step_c, page, store, "Accept Terms", "", config)


@pytest.mark.asyncio
async def test_bug_assert_hidden_false_pass(test_server):
    """
    Test that ASSERT_HIDDEN does NOT falsely PASS when a hidden duplicate
    coexists with a visible element of the same name.
    
    Previously, wait_and_pick_locator returned .first which could pick the
    hidden element, causing to_be_hidden() to trivially PASS even though
    the visible element was clearly not hidden.
    """
    config = BrowserConfig(headless=True, timeout=2000)
    store = VariableStore()

    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            # Hidden mobile nav button + visible desktop button, both named "Menu"
            await page.set_content('''
                <html>
                    <body>
                        <nav style="display:none">
                            <button>Menu</button>
                        </nav>
                        <header>
                            <button>Menu</button>
                        </header>
                    </body>
                </html>
            ''')

            # CASE A: Assert button "Menu" is hidden → should FAIL
            # because at least one "Menu" button (the header one) is visible.
            step_hidden = TestStep(
                line_number=1,
                raw_text='Assert button "Menu" is hidden',
                action_type=ActionType.ASSERT_HIDDEN,
                target_type=TargetType.BUTTON,
                target_identifier="Menu",
                value=""
            )
            with pytest.raises(Exception):
                await _dispatch_action(step_hidden, page, store, "Menu", "", config)

            # CASE B: Assert button "Submit" is hidden → should PASS
            # because there is no "Submit" button at all (effectively hidden).
            step_no_element = TestStep(
                line_number=2,
                raw_text='Assert button "Submit" is hidden',
                action_type=ActionType.ASSERT_HIDDEN,
                target_type=TargetType.BUTTON,
                target_identifier="Submit",
                value=""
            )
            # Should NOT raise — no element means effectively hidden
            await _dispatch_action(step_no_element, page, store, "Submit", "", config)

            # CASE C: Assert button "Menu" is hidden AFTER hiding the visible one
            await page.evaluate('document.querySelector("header button").style.display = "none"')
            # Now both "Menu" buttons are hidden → should PASS
            await _dispatch_action(step_hidden, page, store, "Menu", "", config)
