"""Integration tests for the pytest plugin and custom steps registry."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

# Enable the pytester fixture
pytest_plugins = ["pytester"]


def test_pytest_collect_file_filtering(pytester: pytest.Pytester) -> None:
    """Verify that only test markdown files are collected, and non-test files are ignored."""
    # Create test markdown file
    pytester.makefile(
        ".test.md",
        test_file="""# Test Suite
## Scenario 1
- Navigate to "about:blank"
""",
    )
    # Create non-test markdown file (no scenarios)
    pytester.makefile(
        ".md",
        readme="""# Readme Title
Some random descriptions without any test scenarios.
""",
    )
    # Create spec markdown file
    pytester.makefile(
        ".spec.md",
        spec_file="""# Spec Suite
## Scenario 2
- Navigate to "about:blank"
""",
    )

    # Run pytest collection
    result = pytester.parseconfigure()
    # Find collected items
    collected = pytester.inline_run()
    
    # We can check that the test_file.test.md and spec_file.spec.md tests ran or were collected
    # Let's run pytester and verify the collected test counts.
    res = pytester.runpytest("--collect-only")
    output = res.stdout.str()
    
    assert "test_file.test.md" in output
    assert "spec_file.spec.md" in output
    assert "readme.md" not in output


def test_custom_steps_and_sandbox_execution(pytester: pytest.Pytester, test_server: str) -> None:
    """Test standard and custom steps, async code sandbox, and fixture injection."""
    # Write conftest.py with custom steps and a mock fixture
    pytester.makeconftest(
        f"""
import pytest
from md_e2e import custom_step

@pytest.fixture
def dummy_token():
    return "secret-token-123"

@custom_step(r'Log in via API as user "(?P<email>[^"]+)"')
async def api_login(page, email, dummy_token):
    # Set dummy token in a cookie to verify fixture injection and async execution
    await page.context.add_cookies([{{
        "name": "auth",
        "value": f"{{dummy_token}}-{{email}}",
        "url": "{test_server}"
    }}])

@custom_step(r'Store custom "(?P<val>[^"]+)" in "(?P<var_name>[^"]+)"')
def store_custom_val(store, val, var_name):
    # Synchronous step using the store
    store.store(var_name, val)

@custom_step(r'Assert variable "(?P<var_name>[^"]+)" equals "(?P<expected>[^"]+)"')
def assert_variable_equals(store, var_name, expected):
    assert store.get(var_name) == expected
"""
    )

    # Write a test markdown file
    pytester.makefile(
        ".test.md",
        custom_test=f"""# Custom Steps Test Suite @suite-tag
```python setup
# Verify variable injection in sandbox hook
assert page is not None
assert browser is not None
assert context is not None
assert store is not None
assert context_store is not None
assert config is not None

# Store variable inside sandbox
store.store("SANDBOX_VAR", "sandbox-ok")
```

## Custom step execution scenario @case-tag
- Navigate to "{test_server}/test_app.html"
- Log in via API as user "alice@example.com"
- Store custom "hello-world" in "MY_VAR"
- Assert variable "MY_VAR" equals "hello-world"
- Assert variable "SANDBOX_VAR" equals "sandbox-ok"
- Store text from heading "Welcome to the Test App" as "HEADER_TEXT"
- Assert variable "HEADER_TEXT" equals "Welcome to the Test App"
"""
    )

    # Run pytest
    result = pytester.runpytest("-v", "-m", "case-tag")
    result.assert_outcomes(passed=1, failed=0)


def test_parameterised_scenarios_and_failures(pytester: pytest.Pytester, test_server: str) -> None:
    """Test running parameterised scenarios as separate items, and verify failure formatting."""
    # Write a custom step to assert variable (to check row parameters)
    pytester.makeconftest(
        """
from md_e2e import custom_step

@custom_step(r'Verify username is "(?P<expected>[^"]+)"')
def verify_username(store, expected):
    assert store.get("username") == expected

@custom_step(r'Fail this step intentionally')
def fail_step():
    raise AssertionError("Intentionally failed")
"""
    )

    # Write a test markdown file with parameters
    pytester.makefile(
        ".test.md",
        param_test=f"""# Parameterised Test
## Login Parameterised Scenario
- Verify username is "{{{{username}}}}"

| username |
| --- |
| userA@example.com |
| userB@example.com |

## Failing Scenario
- Fail this step intentionally
"""
    )

    # Run pytest
    result = pytester.runpytest("-v")
    # Should run 2 parameterised cases (passed) and 1 failing scenario (failed)
    result.assert_outcomes(passed=2, failed=1)

    # Check that failure report contains step line and name
    output = result.stdout.str()
    assert "Markdown E2E Failure:" in output
    assert "Step: Fail this step intentionally" in output
    assert "Error: Intentionally failed" in output
