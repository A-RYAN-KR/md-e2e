"""Comprehensive Kitchen Sink End-to-End Test Suite."""

import pytest
from pathlib import Path
from md_e2e.browser import BrowserConfig
from md_e2e.md_parser import parse_markdown
from md_e2e.executor import execute_suite, StepStatus


@pytest.mark.asyncio
async def test_kitchen_sink_full_lifecycle(test_server):
    """Execute a complete lifecycle Markdown test against the Kitchen Sink app."""
    markdown_content = f"""# Kitchen Sink Platform Suite @kitchen-sink

```python setup
store.store("BASE_URL", "{test_server}")
store.store("TEST_USER", "antigravity_dev")
```

## Scenario 1: Authentication Form & Dynamic State @auth
- Navigate to "{{{{BASE_URL}}}}/kitchen_sink.html"
- Assert heading "Kitchen Sink E2E Demo Platform" is visible
- Fill input "Username" with "{{{{TEST_USER}}}}"
- Fill input "Email Address" with "dev@antigravity.io"
- Fill input "Password" with "P@ssw0rd123!"
- Check checkbox "I agree to the terms and privacy policy"
- Check radio "Administrator"
- Select "Quality Assurance" from "Department"
- Click button "Sign In Account"
- Assert text "Welcome back, {{{{TEST_USER}}}}!" is visible
- Assert text "Successfully signed in as {{{{TEST_USER}}}}" is visible
- Store text from "#session-id" as "EXTRACTED_SESSION"
- Assert variable "EXTRACTED_SESSION" equals "AUTH-98765-SECURE"

## Scenario 2: Asynchronous State & Hover Popovers @async
- Navigate to "{{{{BASE_URL}}}}/kitchen_sink.html"
- Click button "Load Order Records"
- Assert text "Order #ORD-77492" is visible
- Assert text "Fulfilled" is visible
- Assert text "$149.99 USD" is visible
- Hover "#btn-hover-target"
- Assert text "Secret Passcode: OMEGA-42" is visible

## Scenario 3: Interactive Tabs & View Switching @tabs
- Navigate to "{{{{BASE_URL}}}}/kitchen_sink.html"
- Assert text "System Status: Normal" is visible
- Click button "Settings"
- Assert text "Global Configuration" is visible
- Uncheck checkbox "Dark Theme Enabled"
- Click button "Audit Logs"
- Assert text "Security Event Stream" is visible

## Scenario 4: Parameterized Inventory Data Matrix @matrix
| sku_code | product_name | stock |
| --- | --- | --- |
| SKU-101 | Quantum Keyboard | 24 in stock |
| SKU-202 | Precision Mouse | 12 in stock |
| SKU-303 | UltraWide Monitor | 8 in stock |

- Navigate to "{{{{BASE_URL}}}}/kitchen_sink.html"
- Assert text "<sku_code>" is visible
- Assert text "<product_name>" is visible
- Assert text "<stock>" is visible
- Fill input "#table-search" with "<sku_code>"
- Assert text "<product_name>" is visible
"""

    suite, parse_errors = parse_markdown(markdown_content)
    assert not parse_errors or all(e.severity == "warning" for e in parse_errors)
    assert len(suite.test_cases) == 4

    config = BrowserConfig(headless=True)
    result = await execute_suite(suite, config=config)

    assert result.total_scenarios == 6  # 3 single scenarios + 3 rows from Scenario 4
    for scenario_res in result.scenario_results:
        assert scenario_res.status == StepStatus.PASSED, f"Scenario '{scenario_res.name}' failed: {scenario_res.error}"
