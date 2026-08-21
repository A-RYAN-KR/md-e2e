"""Integration tests for semantic accessibility locator resolution."""

import http.server
import threading
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.locator import resolve_locator, is_raw_selector
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
            btn_role = resolve_locator(page, TargetType.BUTTON, "Sign In")
            await btn_role.wait_for(state="attached")
            assert await btn_role.get_attribute("id") == "submit-button"
            
            # 2. INPUT TargetType (via Label)
            input_label = resolve_locator(page, TargetType.INPUT, "Email")
            assert await input_label.get_attribute("id") == "email-input"
            
            # 3. INPUT TargetType (via Placeholder)
            input_placeholder = resolve_locator(page, TargetType.INPUT, "Enter your password")
            assert await input_placeholder.get_attribute("id") == "password-input"
            
            # 4. LINK TargetType
            link = resolve_locator(page, TargetType.LINK, "Home")
            assert await link.get_attribute("id") == "home-link"
            
            # 5. HEADING TargetType
            heading = resolve_locator(page, TargetType.HEADING, "Welcome to the Test App")
            assert await heading.get_attribute("id") == "main-heading"
            
            # 6. CHECKBOX TargetType
            checkbox = resolve_locator(page, TargetType.CHECKBOX, "Remember me")
            assert await checkbox.get_attribute("id") == "remember-me-checkbox"
            
            # 7. RADIO TargetType
            radio = resolve_locator(page, TargetType.RADIO, "Male")
            assert await radio.get_attribute("id") == "gender-male"
            
            # 8. TEXT TargetType
            text_el = resolve_locator(page, TargetType.TEXT, "Welcome to the Test App")
            assert await text_el.get_attribute("id") == "main-heading"
            
            # 9. GENERIC target type fallback behavior
            generic_label = resolve_locator(page, TargetType.GENERIC, "Email")
            tag = await generic_label.evaluate("el => el.tagName.toLowerCase()")
            assert tag in ("label", "input")
            
            generic_placeholder = resolve_locator(page, TargetType.GENERIC, "Enter your password")
            assert await generic_placeholder.get_attribute("id") == "password-input"
            
            generic_button = resolve_locator(page, TargetType.GENERIC, "Sign In")
            assert await generic_button.get_attribute("id") == "submit-button"
            
            generic_link = resolve_locator(page, TargetType.GENERIC, "Home")
            assert await generic_link.get_attribute("id") == "home-link"
            
            # 10. Raw selectors
            css_selector = resolve_locator(page, TargetType.GENERIC, "#email-input")
            assert await css_selector.get_attribute("id") == "email-input"
            
            xpath_selector = resolve_locator(page, TargetType.GENERIC, "//input[@id='password-input']")
            assert await xpath_selector.get_attribute("id") == "password-input"
