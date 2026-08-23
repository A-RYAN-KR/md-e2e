<div align="center">

# 📝 md-e2e

### *The Zero-Glue-Code, Markdown-Native E2E Test Automation Framework powered by Playwright*

[![Build Status](https://img.shields.io/github/actions/workflow/status/contributors/md-e2e/e2e.yml?branch=main&style=for-the-badge&logo=github&color=38bdf8)](https://github.com/contributors/md-e2e/actions)
[![PyPI Version](https://img.shields.io/pypi/v/md-e2e?style=for-the-badge&logo=pypi&color=34d399)](https://pypi.org/project/md-e2e)
[![Python Support](https://img.shields.io/pypi/pyversions/md-e2e?style=for-the-badge&logo=python&color=fbbf24)](https://pypi.org/project/md-e2e)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg?style=for-the-badge&logo=ruff)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg?style=for-the-badge&logo=python)](https://github.com/python/mypy)
[![License: MIT](https://img.shields.io/badge/License-MIT-a78bfa.svg?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  <b>Write plain Markdown. Run production-grade Playwright tests. Zero boilerplate required.</b>
</p>

<p align="center">
  <a href="#-why-md-e2e">Why md-e2e?</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-dsl-reference">DSL Reference</a> •
  <a href="#-variables--dynamic-state">Variables</a> •
  <a href="#%EF%B8%8F-self-healing-engine">Self-Healing</a> •
  <a href="#-custom-steps">Custom Steps</a> •
  <a href="#-reports--living-documentation">Reports</a> •
  <a href="#-pytest-integration">Pytest</a> •
  <a href="#%EF%B8%8F-cli-reference">CLI</a>
</p>

</div>

---

## 💡 Why md-e2e?

**md-e2e** allows developers, QA engineers, and product managers to write and execute robust browser automation directly in plain Markdown.

| Framework | Test Format | Glue Code Required? | Resilience | Who Can Edit? |
| :--- | :--- | :---: | :---: | :---: |
| **Cypress / Playwright** | TypeScript / Python | ❌ Direct code | ⚠️ Manual selectors | Engineers only |
| **Cucumber / Behave** | Gherkin `.feature` | 🔴 Heavy (regex steps for every sentence) | ⚠️ Brittle | PMs read, engineers maintain |
| **md-e2e** | **Plain Markdown** | 🟢 **Zero** | 🛡️ **Self-Healing + AI** | **Everyone** |

### Key Features
- **Zero Step Definitions**: Natural language actions resolve to Playwright locators automatically.
- **First-Class `data-testid`**: Seamlessly target icon buttons and complex components via `Click testid "..."`.
- **Hybrid Self-Healing**: Resilient against UI refactors with 5 deterministic safeguards and optional LLM fallback.
- **Data-Driven Matrix**: Run scenarios across data tables with zero extra code.
- **Built-in Tools**: Includes an interactive step-by-step debugger and codegen browser recorder.

---

## 🚀 Quick Start

### 1. Installation

```bash
pip install md-e2e
playwright install --with-deps chromium
```

### 2. Initialize Project

```bash
md-e2e init
```

This sets up:
```text
tests/
├── sample.test.md    # Starter Markdown test suite
└── conftest.py       # Custom step registrations & fixtures
```

### 3. Write a Test (`tests/sample.test.md`)

```markdown
# Sample E2E Test Suite

## Verify Example Domain
- Navigate to "https://example.com"
- Assert heading "Example Domain" is visible
- Assert text "illustrative examples" is visible
- Assert link "More information..." is visible
```

### 4. Run Tests

```bash
# Headless run
md-e2e run tests/

# Headed mode with 500ms delay
md-e2e run tests/ --headed --slowmo 500

# Run specific browser (chromium, firefox, webkit)
md-e2e run tests/ --browser firefox
```

---

## 📐 Test Spec Anatomy

A Markdown test file combines headings, metadata tags, optional Python hooks, and step lists:

````markdown
# E-Commerce Suite @smoke @checkout

```python setup
# Suite setup: runs once before scenarios
store.store("BASE_URL", "https://shop.example.com")
```

## User Checkout @critical
- Navigate to "{{BASE_URL}}/cart"
- Fill input "Email" with "{{RANDOM_EMAIL}}"
- Click button "Checkout"
- Wait for URL contains "/confirmation"
- Assert heading "Order Confirmed" is visible
- Store text from heading "Order #" as "ORDER_ID"

```python teardown
# Scenario teardown: runs after scenario (even on failure)
print(f"Finished order: {store.get('ORDER_ID')}")
```
````

---

## 📖 DSL Reference

All step keywords are case-insensitive. Values can use double quotes (`"`), single quotes (`'`), or backticks (`` ` ``).

### Navigation & Page Actions
| Action | Example |
| :--- | :--- |
| `Navigate to "<url>"` / `Go to "<url>"` | `- Navigate to "https://example.com/login"` |
| `Reload page` / `Reload` | `- Reload page` |

### Clicks & Mouse
| Action | Example |
| :--- | :--- |
| `Click button "<name>"` | `- Click button "Sign In"` |
| `Click link "<name>"` | `- Click link "Forgot Password?"` |
| `Click "<text>"` | `- Click "Terms of Service"` |
| `Click testid "<id>"` | `- Click testid "theme-toggle-btn"` |
| `Hover "<name>"` / `Hover over "<name>"` | `- Hover over "User Profile"` |
| `Hover testid "<id>"` | `- Hover testid "tooltip-trigger"` |

### Inputs & Forms
| Action | Example |
| :--- | :--- |
| `Fill input "<field>" with "<val>"` | `- Fill input "Email" with "user@test.com"` |
| `Fill "<field>" with "<val>"` | `- Fill "Password" with "Secret123!"` |
| `Fill testid "<id>" with "<val>"` | `- Fill testid "search-box" with "laptop"` |
| `Select "<option>" from "<dropdown>"` | `- Select "United States" from "Country"` |
| `Check checkbox "<name>"` / `Check "<name>"` | `- Check checkbox "Subscribe to newsletter"` |
| `Uncheck checkbox "<name>"` / `Uncheck "<name>"` | `- Uncheck checkbox "Remember Me"` |
| `Check testid "<id>"` / `Uncheck testid "<id>"` | `- Check testid "terms-agree"` |
| `Upload "<file>" to "<input>"` | `- Upload "fixtures/doc.pdf" to "Resume"` |
| `Press "<key>"` | `- Press "Enter"` or `- Press "Control+a"` |

### Assertions
| Action | Example |
| :--- | :--- |
| `Assert heading "<txt>" is visible` | `- Assert heading "Dashboard" is visible` |
| `Assert button "<txt>" is visible` | `- Assert button "Submit" is visible` |
| `Assert text "<txt>" is visible` / `Assert "<txt>" is visible` | `- Assert text "Welcome back!" is visible` |
| `Assert testid "<id>" is visible` | `- Assert testid "cart-badge" is visible` |
| `Assert heading "<txt>" is hidden` / `Assert "<txt>" is hidden` | `- Assert "Loading..." is hidden` |
| `Assert testid "<id>" is hidden` | `- Assert testid "spinner" is hidden` |
| `Assert URL is "<url>"` / `contains "<str>"` / `matches "<regex>"` | `- Assert URL contains "/dashboard"` |
| `Assert title is "<title>"` / `contains "<str>"` | `- Assert title contains "Overview"` |
| `Assert input "<field>" value is "<val>"` / `contains "<val>"` | `- Assert input "Username" value is "admin"` |
| `Assert variable "<name>" is "<val>"` / `contains "<val>"` | `- Assert variable "STATUS" is "active"` |

### Waiting & Synchronization
| Action | Example |
| :--- | :--- |
| `Wait <N> seconds` | `- Wait 3 seconds` |
| `Wait for network idle` | `- Wait for network idle` |
| `Wait for URL contains "<str>"` / `is "<url>"` / `matches "<regex>"` | `- Wait for URL contains "/checkout"` |

### Storing Variables
| Action | Example |
| :--- | :--- |
| `Store text from heading "<target>" as "<VAR>"` | `- Store text from heading "Total" as "TOTAL_PRICE"` |
| `Store text from "<target>" as "<VAR>"` | `- Store text from "Order ID" as "ORDER_ID"` |
| `Store text from testid "<id>" as "<VAR>"` | `- Store text from testid "order-num" as "ORDER_ID"` |

---

## 🔄 Variables & Dynamic State

Variables are interpolated using `{{VAR}}`, `{{ VAR }}`, or `${VAR}`.

### Built-in Generators
- `{{RANDOM_STRING}}`: Random 12-char alphanumeric string (e.g., `k8f2m9x0w1q4`).
- `{{RANDOM_EMAIL}}`: Unique email (e.g., `test_9x2b4m1q@example.com`).
- `{{TIMESTAMP}}`: Unix epoch timestamp string (e.g., `1740000000`).

### Environment Variables & State Pipeline
Prefix environment variables with `ENV_`:
```markdown
- Navigate to "{{ENV_BASE_URL}}/login"
- Fill input "API Key" with "{{ENV_SECRET_KEY}}"
```

Pass state dynamically across steps:
```markdown
- Click button "Create Token"
- Store text from heading "Token" as "AUTH_KEY"
- Fill input "Enter Token" with "{{AUTH_KEY}}"
```

---

## 📊 Data-Driven Testing

Execute scenarios across parameter tables by placing a Markdown table below the scenario heading:

```markdown
## User Login Matrix @data-driven
| username | password  | expected_status |
| alice    | pass123   | Welcome, Alice  |
| bob      | secret456 | Welcome, Bob    |

- Navigate to "https://example.com/login"
- Fill input "Username" with "{{username}}"
- Fill input "Password" with "{{password}}"
- Click button "Sign In"
- Assert text "{{expected_status}}" is visible
```

---

## 🛡️ Self-Healing Engine

When UI selectors change (e.g., button labels or layout tweaks), md-e2e intercepts locator timeouts, snapshots visible interactive elements, and resolves the target using local heuristics or optional AI fallback.

### Production Safeguards
1. **Similarity Threshold**: Match ratio must be $\ge 0.70$.
2. **Role Confinement**: Buttons only heal to buttons, inputs to inputs.
3. **Ambiguity Delta**: Top candidate must lead second place by $\ge 0.12$.
4. **Opposing Verb Guard**: Never heals antonyms (`Save` $\neq$ `Delete`, `Cancel` $\neq$ `Confirm`).
5. **Negative Assertion Bypass**: `Assert ... is hidden` never heals.
6. **Metadata Stripping**: Automatically handles counter badges (`Customer Reviews (2)` matches `Customer Reviews`).

### Enabling AI / LLM Fallback (Tier 2)
Set your API key via environment variable:
```bash
export OPENAI_API_KEY="sk-..."       # Linux/macOS
$env:OPENAI_API_KEY="sk-..."        # Windows PowerShell
```
Or pass directly: `md-e2e run tests/ --llm-api-key "sk-..."`.

### Auto-Generated Git Patches
At the end of a run, healed steps produce a `git apply`-compatible patch:
```diff
--- a/tests/checkout.test.md
+++ b/tests/checkout.test.md
@@ -14,1 +14,1 @@
- - Click button "Proceed to Checkout"
+ - Click button "Complete Purchase"
```

---

## 🧩 Custom Steps

Extend the DSL with Python step handlers in `tests/conftest.py` (auto-discovered on execution):

```python
from md_e2e import custom_step

@custom_step(r'Clear all browser cookies')
async def clear_cookies(page):
    await page.context.clear_cookies()

@custom_step(r'Log in as user "(?P<email>[^"]+)" with role "(?P<role>[^"]+)"')
async def custom_login(page, email: str, role: str, store):
    await page.goto("https://example.com/login")
    await page.fill('[name="email"]', email)
    store.store("CURRENT_USER", email)
```

Use in tests:
```markdown
## Custom Step Scenario
- Clear all browser cookies
- Log in as user "admin@test.com" with role "Admin"
- Assert heading "Admin Dashboard" is visible
```

---

## 🐛 Debugger & Recorder

### Interactive Step Debugger
Step through actions in real time with visual browser highlights:
```bash
md-e2e run tests/sample.test.md --step
```
- `Enter`: Next step
- `r`: Retry step
- `e`: Edit step on-the-fly
- `s`: Skip step
- `q`: Quit execution

### Action Recorder (Codegen)
Generate Markdown tests interactively by browsing:
```bash
md-e2e record "https://example.com" -o tests/recorded.test.md
```

---

## 📊 Reports & Living Documentation

Generate Markdown PR summaries and interactive HTML dashboards:

```bash
md-e2e run tests/ --report-md summary.md --report-html report.html
```

- **`summary.md`**: GitHub PR comment-ready summary with test outcome badges and collapsible error traces.
- **`report.html`**: Zero-dependency dashboard with search filters, embedded screenshots, video recordings, and trace viewer downloads.

---

## 🧪 Pytest Integration

Markdown tests are automatically collected and executed under `pytest`:

```bash
# Run all tests
pytest -v

# Run tagged scenarios
pytest -m "smoke and not slow" -v

# Run with headed browser & custom timeout
pytest --md-headed --md-timeout 15000
```

---

## ⚙️ CLI Reference

### `md-e2e run`
```bash
md-e2e run <path> [options]
```

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `path` | Argument | *(required)* | Path to test file or directory |
| `--headed` | Flag | `False` | Run with visible browser window |
| `--browser` | Choice | `chromium` | Engine (`chromium`, `firefox`, `webkit`) |
| `--slowmo` | Integer | `0` | Delay between actions in milliseconds |
| `--timeout` | Integer | `30000` | Step timeout in milliseconds |
| `--step` | Flag | `False` | Enable interactive step debugger |
| `--healing / --no-healing` | Flag | `True` | Toggle self-healing engine |
| `--clean-session` | Flag | `False` | Isolate variables per scenario |
| `--verbose / -v` | Flag | `False` | Show full stack traces and logs |
| `--llm-api-key` | String | `None` | API key for LLM healing fallback |
| `--report-md` | Path | `None` | Export Markdown summary report |
| `--report-html` | Path | `None` | Export interactive HTML report |

### Other Commands
- `md-e2e init`: Scaffold `tests/` directory with sample files.
- `md-e2e record <url> [-o out.test.md]`: Launch browser codegen session.
- `md-e2e info <path>`: Inspect suites, scenarios, and tags.

---

## 🤖 CI/CD Integration

### GitHub Actions (`.github/workflows/e2e.yml`)

```yaml
name: E2E Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: |
          pip install md-e2e
          playwright install --with-deps chromium
      - run: md-e2e run tests/ --report-md summary.md --report-html report.html
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - if: always()
        run: cat summary.md >> $GITHUB_STEP_SUMMARY
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: html-report
          path: report.html
```

---

## 💬 Special Characters & Quoting

| Syntax | Description | Example |
| :--- | :--- | :--- |
| `"..."` | Standard double quotes | `- Click button "Login"` |
| `'...'` | Single quotes for nested double quotes | `- Assert text 'Results for "Shoes"' is visible` |
| `` `...` `` | Backticks for mixed quotes | `` - Assert text `User "John's" Profile` is visible `` |
| `\"` | Escaped double quotes | `- Assert text "Results for \"Shoes\"" is visible` |

*Note: Slashes in element names (e.g. `Light/Dark`) are automatically escaped.*

---

## 🔒 Browser Context Isolation

By default, browser contexts (cookies, localStorage) are clean per scenario, while variables are shared across the suite. To enforce completely isolated variables per scenario, pass `--clean-session`:

```bash
md-e2e run tests/ --clean-session
```

---

## ❓ Troubleshooting

| Issue | Resolution |
| :--- | :--- |
| `Executable doesn't exist` | Run `playwright install --with-deps chromium` |
| `StepNotImplementedError` | Verify custom step regex in `tests/conftest.py` |
| `UnicodeEncodeError` on Windows | Resolved natively in md-e2e v0.2.0+ via UTF-8 stdout wrapping |
| Flaky timing in SPA apps | Add `Wait for URL contains "..."` or `Wait for network idle` |
| Ambiguous `<select>` matching | `Select ... from ...` prioritizes `<select>` tags by label / name |

---

## 🤝 Contributing

```bash
git clone https://github.com/contributors/md-e2e.git
cd md-e2e
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install --with-deps chromium
pytest -v
```

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
