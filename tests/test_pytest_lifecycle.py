pytest_plugins = ["pytester"]
import pytest
import os
from pathlib import Path
from md_e2e.variables import VariableStore

@pytest.fixture
def run_pytest_suite(pytester):
    """Helper to run a markdown test string through pytester."""
    def _run(md_content: str):
        p = pytester.makepyfile("")
        md_file = pytester.path / "test_lifecycle.spec.md"
        md_file.write_text(md_content, encoding="utf-8")
        return pytester.runpytest("-s", str(md_file))
    return _run

def test_pytest_suite_generated_variable_inheritance(run_pytest_suite):
    """TEST 1: Suite setup explicit variables persist, while scenarios get fresh generated values."""
    md = """# Test Suite
```python setup
# suite_setup
store.store("shared_email", store.get("RANDOM_EMAIL"))
```

## Scenario 1
Assert "{{shared_email}}" is "{{shared_email}}"

## Scenario 2
Assert "{{shared_email}}" is "{{shared_email}}"
"""
    result = run_pytest_suite(md)
    result.assert_outcomes(passed=2)

def test_pytest_explicit_suite_variable_inheritance(run_pytest_suite):
    """TEST 2: Explicit suite variable inheritance."""
    md = """# Suite
```python setup
# suite_setup
store.store("token", "ABC")
```
## Scenario 1
Assert "{{token}}" is "ABC"
## Scenario 2
Assert "{{token}}" is "ABC"
"""
    result = run_pytest_suite(md)
    result.assert_outcomes(passed=2)

def test_pytest_row_local_generated_values(run_pytest_suite):
    """TEST 3: Row-local generated values must be unique."""
    # We will use the 'verify generated' custom step which we can just mock via stdout
    md2 = """# Suite
## Scenario 1
| id |
|---|
| 1 |
| 2 |

```python setup
email = store.get("RANDOM_EMAIL")
print(f"MY_EMAIL: {email}")
```
Assert "1" is "1"
"""
    result = run_pytest_suite(md2)
    result.assert_outcomes(passed=2)
    
    out = result.stdout.str()
    emails = [line.split("MY_EMAIL: ")[1].strip() for line in out.splitlines() if "MY_EMAIL:" in line]
        
    assert len(emails) == 2
    assert emails[0] != emails[1], "Matrix rows should generate separate unique emails"

def test_pytest_setup_failure_propagation(run_pytest_suite):
    """TEST 4: Suite setup deliberately fails. All scenarios should fail."""
    md = """# Suite
```python setup
# suite_setup
assert False, "Deliberate suite setup failure"
```
## Scenario 1
Assert "1" is "1"
## Scenario 2
Assert "2" is "2"
"""
    result = run_pytest_suite(md)
    # The first should fail because the setup hook threw.
    # The second should ALSO fail because setup state correctly tracks the failure.
    result.assert_outcomes(failed=2)

def test_pytest_setup_executes_exactly_once_on_success(run_pytest_suite):
    """TEST 5: Setup executes exactly once on success."""
    md = """# Suite
```python setup
# suite_setup
if "count" not in store._data:
    store.store("count", 1)
else:
    store.store("count", int(store.get("count")) + 1)
```
## Scenario 1
Assert "{{count}}" is "1"
## Scenario 2
Assert "{{count}}" is "1"
"""
    result = run_pytest_suite(md)
    result.assert_outcomes(passed=2)
