"""Integration tests for semantic accessibility locator resolution."""

import http.server
import threading
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.locator import resolve_locator, is_raw_selector
from md_e2e.executor import wait_and_pick_locator
from md_e2e.models import TargetType



# ── Selector Detection Tests ────────────────────────────────────────────────

def test_is_raw_selector():
    assert is_raw_selector("#submit-btn") is True
    assert is_raw_selector(".btn-primary") is True
    assert is_raw_selector("//button") is True
    assert is_raw_selector("css=button") is True
    assert is_raw_selector("xpath=//button") is True
    assert is_raw_selector("data-testid=login") is True
    assert is_raw_selector("[data-testid='login']") is True
    assert is_raw_selector("div >> span") is True
    
    assert is_raw_selector("Submit") is False
    assert is_raw_selector("button 'Submit'") is False


# ── Locator Resolution Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_locators_against_test_app(test_server):
    config = BrowserConfig(headless=True)
    async with BrowserSession(config) as session:
        async with session.new_context() as (context, page):
            await page.goto(f"{test_server}/test_app.html")
            
            # 1. BUTTON TargetType
            btn_tiers = resolve_locator(page, TargetType.BUTTON, "Sign In")
            btn_role = await wait_and_pick_locator(btn_tiers, 5000)
            await btn_role.wait_for(state="attached")
            assert await btn_role.get_attribute("id") == "submit-button"
            
            # 2. INPUT TargetType (via Label)
            input_label_tiers = resolve_locator(page, TargetType.INPUT, "Email")
            input_label = await wait_and_pick_locator(input_label_tiers, 5000)
            assert await input_label.get_attribute("id") == "email-input"
            
            # 3. INPUT TargetType (via Placeholder)
            input_placeholder_tiers = resolve_locator(page, TargetType.INPUT, "Enter your password")
            input_placeholder = await wait_and_pick_locator(input_placeholder_tiers, 5000)
            assert await input_placeholder.get_attribute("id") == "password-input"
            
            # 4. LINK TargetType
            link_tiers = resolve_locator(page, TargetType.LINK, "Home")
            link = await wait_and_pick_locator(link_tiers, 5000)
            assert await link.get_attribute("id") == "home-link"
            
            # 5. HEADING TargetType
            heading_tiers = resolve_locator(page, TargetType.HEADING, "Welcome to the Test App")
            heading = await wait_and_pick_locator(heading_tiers, 5000)
            assert await heading.get_attribute("id") == "main-heading"
            
            # 6. CHECKBOX TargetType
            checkbox_tiers = resolve_locator(page, TargetType.CHECKBOX, "Remember me")
            checkbox = await wait_and_pick_locator(checkbox_tiers, 5000)
            assert await checkbox.get_attribute("id") == "remember-me-checkbox"
            
            # 7. RADIO TargetType
            radio_tiers = resolve_locator(page, TargetType.RADIO, "Male")
            radio = await wait_and_pick_locator(radio_tiers, 5000)
            assert await radio.get_attribute("id") == "gender-male"
            
            # 8. TEXT TargetType
            text_el_tiers = resolve_locator(page, TargetType.TEXT, "Welcome to the Test App")
            text_el = await wait_and_pick_locator(text_el_tiers, 5000)
            assert await text_el.get_attribute("id") == "main-heading"
            
            # 9. GENERIC target type fallback behavior
            generic_label_tiers = resolve_locator(page, TargetType.GENERIC, "Email")
            generic_label = await wait_and_pick_locator(generic_label_tiers, 5000)
            tag = await generic_label.evaluate("el => el.tagName.toLowerCase()")
            assert tag in ("label", "input")
            
            generic_placeholder_tiers = resolve_locator(page, TargetType.GENERIC, "Enter your password")
            generic_placeholder = await wait_and_pick_locator(generic_placeholder_tiers, 5000)
            assert await generic_placeholder.get_attribute("id") == "password-input"
            
            generic_button_tiers = resolve_locator(page, TargetType.GENERIC, "Sign In")
            generic_button = await wait_and_pick_locator(generic_button_tiers, 5000)
            assert await generic_button.get_attribute("id") == "submit-button"
            
            generic_link_tiers = resolve_locator(page, TargetType.GENERIC, "Home")
            generic_link = await wait_and_pick_locator(generic_link_tiers, 5000)
            assert await generic_link.get_attribute("id") == "home-link"
            
            # 10. Raw selectors
            css_selector_tiers = resolve_locator(page, TargetType.GENERIC, "#email-input")
            css_selector = await wait_and_pick_locator(css_selector_tiers, 5000)
            assert await css_selector.get_attribute("id") == "email-input"
            
            xpath_selector_tiers = resolve_locator(page, TargetType.GENERIC, "//input[@id='password-input']")
            xpath_selector = await wait_and_pick_locator(xpath_selector_tiers, 5000)
            assert await xpath_selector.get_attribute("id") == "password-input"
