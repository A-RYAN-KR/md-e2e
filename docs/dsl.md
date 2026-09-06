# Markdown DSL Reference

md-e2e executes test specifications written in a simple, highly readable Markdown dialect. No glue code or step definition files are required.

---

## 📐 Test File Structure

A Markdown test file consists of a Suite Heading (`H1`), optional Python setup/teardown blocks, Scenarios (`H2`), optional parameter matrix tables, and bulleted step lists.

````markdown
# E-Commerce Suite @smoke @checkout

```python setup
# Runs once before scenarios; variables stored here are available suite-wide
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
# Runs after the scenario finishes (even if steps failed)
print(f"Checkout completed with order: {store.get('ORDER_ID')}")
```
````

---

## 🏷️ Tags & Metadata

Tags can be declared on Suite (`#`) or Scenario (`##`) headings using `@tag_name`:

```markdown
# Authentication Suite @auth @nightly

## Invalid Password Flow @negative @fast
```

When executing with `pytest`, tags are automatically mapped to pytest markers (`pytest -m "auth and not negative"`).

---

## 📖 Step Vocabulary

All step keywords are case-insensitive. Element targets and values can be enclosed in double quotes (`"`), single quotes (`'`), or backticks (`` ` ``).

### Navigation & Page Actions
| Action | Description | Example |
| :--- | :--- | :--- |
| `Navigate to "<url>"` | Navigate browser to target URL | `- Navigate to "https://example.com/login"` |
| `Go to "<url>"` | Alias for navigate | `- Go to "https://example.com/dashboard"` |
| `Reload page` | Reload the active page | `- Reload page` |

### Clicks & Mouse Actions
| Action | Description | Example |
| :--- | :--- | :--- |
| `Click button "<name>"` | Click button by accessible name or text | `- Click button "Sign In"` |
| `Click link "<name>"` | Click link by accessible text or href | `- Click link "Forgot Password?"` |
| `Click "<text>"` | Click generic element by text content | `- Click "Terms of Service"` |
| `Click testid "<id>"` | Click element with `data-testid="<id>"` | `- Click testid "theme-toggle-btn"` |
| `Hover "<name>"` | Hover over element | `- Hover over "User Profile"` |
| `Hover testid "<id>"` | Hover over element with test ID | `- Hover testid "tooltip-trigger"` |

### Inputs & Forms
| Action | Description | Example |
| :--- | :--- | :--- |
| `Fill input "<field>" with "<val>"` | Fill input field by label, placeholder, or name | `- Fill input "Email" with "user@test.com"` |
| `Fill "<field>" with "<val>"` | Generic fill action | `- Fill "Password" with "Secret123!"` |
| `Fill testid "<id>" with "<val>"` | Fill input identified by `data-testid` | `- Fill testid "search-box" with "laptop"` |
| `Select "<opt>" from "<dropdown>"` | Select option by label or value (budgeted wait) | `- Select "United States" from "Country"` |
| `Check checkbox "<name>"` | Check a checkbox input | `- Check checkbox "Subscribe to newsletter"` |
| `Uncheck checkbox "<name>"` | Uncheck a checkbox input | `- Uncheck checkbox "Remember Me"` |
| `Check testid "<id>"` | Check checkbox by `data-testid` | `- Check testid "terms-agree"` |
| `Uncheck testid "<id>"` | Uncheck checkbox by `data-testid` | `- Uncheck testid "opt-in"` |
| `Upload "<file>" to "<input>"` | Attach a local file to file input | `- Upload "fixtures/doc.pdf" to "Resume"` |
| `Press "<key>"` | Send keyboard keypress or shortcut | `- Press "Enter"` or `- Press "Control+a"` |

### Assertions & Verifications
| Action | Description | Example |
| :--- | :--- | :--- |
| `Assert heading "<txt>" is visible` | Verify heading element visibility | `- Assert heading "Dashboard" is visible` |
| `Assert button "<txt>" is visible` | Verify button element visibility | `- Assert button "Submit" is visible` |
| `Assert text "<txt>" is visible` | Verify text appears in page content | `- Assert text "Welcome back!" is visible` |
| `Assert testid "<id>" is visible` | Verify element with `data-testid` is visible | `- Assert testid "cart-badge" is visible` |
| `Assert heading "<txt>" is hidden` | Verify heading is hidden or absent | `- Assert heading "Banner" is hidden` |
| `Assert "<txt>" is hidden` | Verify text or element is hidden | `- Assert "Loading spinner" is hidden` |
| `Assert testid "<id>" is hidden` | Verify test ID element is hidden | `- Assert testid "spinner" is hidden` |
| `Assert URL contains "<str>"` | Check current page URL | `- Assert URL contains "/dashboard"` |
| `Assert URL is "<url>"` | Exact match on page URL | `- Assert URL is "https://example.com/"` |
| `Assert URL matches "<regex>"` | Regex match on page URL | `- Assert URL matches "https://.*/orders/\\d+"` |
| `Assert title contains "<str>"` | Check browser document title | `- Assert title contains "Overview"` |
| `Assert title is "<title>"` | Exact match on page title | `- Assert title is "Home Page"` |
| `Assert input "<field>" value is "<val>"` | Check value of input or form field | `- Assert input "Username" value is "admin"` |
| `Assert variable "<name>" is "<val>"` | Verify stored variable value | `- Assert variable "STATUS" is "active"` |

### Waiting & Synchronization
| Action | Description | Example |
| :--- | :--- | :--- |
| `Wait <N> seconds` | Explicit pause in seconds | `- Wait 3 seconds` |
| `Wait for network idle` | Wait until network connections settle | `- Wait for network idle` |
| `Wait for URL contains "<str>"` | Asynchronously poll until URL contains string | `- Wait for URL contains "/checkout"` |

### Storing Variables
| Action | Description | Example |
| :--- | :--- | :--- |
| `Store text from heading "<t>" as "<V>"` | Extract heading text into variable | `- Store text from heading "Total" as "PRICE"` |
| `Store text from "<t>" as "<V>"` | Extract element text (prefers visible) | `- Store text from "Order ID" as "ORDER_ID"` |
| `Store text from testid "<id>" as "<V>"` | Extract text by test ID | `- Store text from testid "order-num" as "ID"` |

---

## 🎯 Raw Selectors vs Natural Language

md-e2e supports both human-readable text targets and technical Playwright/CSS selectors:

### Technical Selectors
- **CSS Selectors**: `#id`, `.class-name`, `button.primary`
- **Attribute Selectors**: `input[type="text"]`, `[disabled]`, `[data-active]`
- **Chained Combinators**: `div >> span`, `div >> input[type="text"]`, `form.login >> input#email`
- **Playwright Engines**: `css=button`, `xpath=//button`, `data-testid=my-btn`
- **Pseudo-Classes**: `:visible`, `:has-text(...)`

### Natural Language Safety
Phrases that resemble selector syntax (e.g., `[Save]`, `[Cancel]`, `A >> B`, `Next >> Page`) are intelligently distinguished and treated strictly as plain text, ensuring natural test specs never fail due to unexpected parser errors.

---

## 🔄 Dynamic Variables

Variables are interpolated using `{{VAR}}`, `{{ VAR }}`, or `${VAR}`.

### Built-in Value Generators
- `{{RANDOM_STRING}}`: Unique 12-character alphanumeric string (e.g., `k8f2m9x0w1q4`).
- `{{RANDOM_EMAIL}}`: Fresh unique email address (e.g., `test_9x2b4m1q@example.com`).
- `{{TIMESTAMP}}`: Current Unix epoch timestamp in seconds (e.g., `1740000000`).

### Environment Variables
Prefix system environment variables with `ENV_`:
```markdown
- Navigate to "{{ENV_BASE_URL}}/login"
- Fill input "API Key" with "{{ENV_SECRET_KEY}}"
```

---

## 📊 Data-Driven Parameter Matrix

Execute a scenario repeatedly with different inputs by including a Markdown table immediately below the scenario heading:

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

### Complete Cross-Row Isolation
Each matrix row is executed independently with deep-copied AST steps. Variables or state modifications within one row cannot leak or corrupt subsequent iterations.

---

## 🧩 Custom Python Steps

Extend the DSL by registering custom step handlers in `tests/conftest.py`:

```python
from md_e2e import custom_step

@custom_step(r'Clear browser local storage')
async def clear_storage(page):
    await page.evaluate("localStorage.clear()")

@custom_step(r'Log in as "(?P<username>[^"]+)" with role "(?P<role>[^"]+)"')
async def login_role(page, username: str, role: str, store):
    await page.goto("https://example.com/login")
    await page.fill('#user', username)
    await page.click('#submit')
    store.store("USER_ROLE", role)
```

Use directly in Markdown:
```markdown
## Admin Scenario
- Clear browser local storage
- Log in as "admin@company.com" with role "SuperAdmin"
- Assert heading "Management Console" is visible
```
