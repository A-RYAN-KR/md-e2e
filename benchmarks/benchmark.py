"""Performance benchmark script for md-e2e.

Compares the execution speed and overhead of md-e2e against raw Playwright Python
scripts to measure the parsing, locator resolution, and execution overhead.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright

from md_e2e.models import TestSuite, TestCase, TestStep, ActionType, TargetType
from md_e2e.browser import BrowserConfig
from md_e2e.executor import execute_suite


# Equivalent raw Playwright Python execution (launches browser once, context per iteration)
async def run_raw_playwright(iterations: int) -> float:
    t0 = time.perf_counter()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for _ in range(iterations):
            context = await browser.new_context()
            page = await context.new_page()
            # Navigate
            await page.goto("about:blank", wait_until="domcontentloaded")
            # Assertion
            title = await page.title()
            assert title == ""
            await context.close()
        await browser.close()
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed / iterations


# md-e2e Execution (launches browser once, executes iterations scenarios in one suite run)
async def run_md_e2e(iterations: int) -> float:
    # Build equivalent suite with multiple scenarios programmatically
    scenarios = []
    for i in range(iterations):
        scenarios.append(
            TestCase(
                name=f"Benchmark Scenario {i}",
                line_number=2,
                steps=[
                    TestStep(
                        raw_text='- Navigate to "about:blank"',
                        line_number=3,
                        action_type=ActionType.NAVIGATE,
                        target_identifier="about:blank",
                    ),
                    TestStep(
                        raw_text='- Assert title is ""',
                        line_number=4,
                        action_type=ActionType.ASSERT_TITLE,
                        target_identifier="is",
                        value="",
                    )
                ]
            )
        )
    
    suite = TestSuite(
        name="Benchmark Suite",
        test_cases=scenarios
    )

    config = BrowserConfig(browser_type="chromium", headless=True, enable_healing=False)
    
    t0 = time.perf_counter()
    await execute_suite(suite, config)
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed / iterations


async def main():
    iterations = 20
    print(f"Running benchmarks ({iterations} iterations)...")
    
    # Warmup
    await run_raw_playwright(2)
    await run_md_e2e(2)

    raw_avg = await run_raw_playwright(iterations)
    mde2e_avg = await run_md_e2e(iterations)

    overhead = mde2e_avg - raw_avg
    overhead_pct = (overhead / raw_avg) * 100

    print("=" * 60)
    print(" md-e2e Performance Benchmark Results")
    print("=" * 60)
    print(f"Raw Playwright average per iteration: {raw_avg:.2f} ms")
    print(f"md-e2e average per iteration:         {mde2e_avg:.2f} ms")
    print("-" * 60)
    print(f"Execution Overhead per iteration:     {overhead:.2f} ms ({overhead_pct:.2f}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
