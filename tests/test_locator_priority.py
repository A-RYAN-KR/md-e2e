"""Regression tests for locator semantic priority and DOM-order inversion."""

import pytest
from playwright.async_api import Page, expect

from md_e2e.browser import BrowserConfig, BrowserSession
from md_e2e.locator import resolve_locator
from md_e2e.executor import wait_and_pick_locator
from md_e2e.models import TargetType


@pytest.fixture
def browser_config():
    return BrowserConfig(headless=True)


@pytest.mark.asyncio
async def test_semantic_priority(test_server, browser_config):
    """TEST 1: Semantic priority over DOM order.
    
    If an h2 and a button both match 'Login', the button should be clicked
    even if the h2 appears first.
    """
    async with BrowserSession(browser_config) as session:
        async with session.new_context() as (context, page):
            html = '''
            <h2 id="heading" onclick="window.clicked='heading'">Login</h2>
            <button id="btn" onclick="window.clicked='button'">Login</button>
            <script>window.clicked='none';</script>
            '''
            await page.set_content(html)
            
            tiers = resolve_locator(page, TargetType.GENERIC, "Login")
            locator = await wait_and_pick_locator(tiers, 5000)
            await locator.click()
            
            clicked = await page.evaluate("window.clicked")
            assert clicked == "button"


@pytest.mark.asyncio
async def test_reverse_dom_order(test_server, browser_config):
    """TEST 2: Reverse DOM order.
    
    Ensure that semantic priority still works if the button is first.
    """
    async with BrowserSession(browser_config) as session:
        async with session.new_context() as (context, page):
            html = '''
            <button id="btn" onclick="window.clicked='button'">Login</button>
            <h2 id="heading" onclick="window.clicked='heading'">Login</h2>
            <script>window.clicked='none';</script>
            '''
            await page.set_content(html)
            
            tiers = resolve_locator(page, TargetType.GENERIC, "Login")
            locator = await wait_and_pick_locator(tiers, 5000)
            await locator.click()
            
            clicked = await page.evaluate("window.clicked")
            assert clicked == "button"


@pytest.mark.asyncio
async def test_hidden_duplicate(test_server, browser_config):
    """TEST 3: Hidden duplicate element.
    
    Playwright's get_by_role("button") follows ARIA spec and excludes elements
    hidden via display:none from the role tree. So the GENERIC tier 0 locator
    only matches the visible button. The framework does NOT add its own visibility
    filtering — Playwright's semantic role query handles it naturally.
    
    The visible button is correctly selected and the subsequent Playwright action
    (e.g. click()) succeeds on the actionable element.
    """
    async with BrowserSession(browser_config) as session:
        async with session.new_context() as (context, page):
            html = '''
            <nav style="display:none">
                <button id="hidden-btn">Submit</button>
            </nav>
            <nav>
                <button id="visible-btn">Submit</button>
            </nav>
            '''
            await page.set_content(html)
            
            tiers = resolve_locator(page, TargetType.GENERIC, "Submit")
            locator = await wait_and_pick_locator(tiers, 5000)
            
            # get_by_role("button") excludes the hidden button per ARIA spec.
            # The visible button is correctly picked from the same semantic tier.
            element_id = await locator.evaluate("el => el.id")
            assert element_id == "visible-btn"


@pytest.mark.asyncio
async def test_duplicate_same_tier(test_server, browser_config):
    """TEST 4: Duplicate same-tier elements.
    
    If multiple elements exist in the exact SAME semantic tier, what happens?
    Because wait_and_pick_locator currently returns `tier.first`, it explicitly bypasses
    Playwright's strict mode violation and simply returns the first in the DOM for that tier.
    """
    async with BrowserSession(browser_config) as session:
        async with session.new_context() as (context, page):
            html = '''
            <button id="btn1">Save</button>
            <button id="btn2">Save</button>
            '''
            await page.set_content(html)
            
            tiers = resolve_locator(page, TargetType.BUTTON, "Save")
            locator = await wait_and_pick_locator(tiers, 5000)
            
            element_id = await locator.evaluate("el => el.id")
            assert element_id == "btn1"


@pytest.mark.asyncio
async def test_raw_selectors(test_server, browser_config):
    """TEST 5: Raw selectors."""
    async with BrowserSession(browser_config) as session:
        async with session.new_context() as (context, page):
            html = '''
            <div id="login-container">
                <button class="btn-primary" data-testid="login">Sign In</button>
            </div>
            '''
            await page.set_content(html)
            
            # ID
            tiers = resolve_locator(page, TargetType.GENERIC, "#login-container")
            assert len(tiers) == 1
            loc = await wait_and_pick_locator(tiers, 5000)
            assert await loc.evaluate("el => el.id") == "login-container"
            
            # Class
            tiers = resolve_locator(page, TargetType.GENERIC, ".btn-primary")
            loc = await wait_and_pick_locator(tiers, 5000)
            assert await loc.evaluate("el => el.className") == "btn-primary"
            
            # TestID
            tiers = resolve_locator(page, TargetType.TESTID, "login")
            loc = await wait_and_pick_locator(tiers, 5000)
            assert await loc.evaluate("el => el.dataset.testid") == "login"
