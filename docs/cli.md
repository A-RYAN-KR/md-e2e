# Standalone CLI Command Reference

md-e2e includes a rich standalone command-line tool (`md-e2e`) designed for rapid local testing, interactive debugging, test generation, and CI/CD pipelines.

---

## 🛠️ Project Initialization

Scaffold a new test environment in any existing repository:

```bash
md-e2e init
```

This generates:
- `tests/sample.test.md`: A starter test specification demonstrating common DSL verbs.
- `tests/conftest.py`: Configuration template for custom Python step definitions.

---

## 🚀 Test Execution (`md-e2e run`)

Execute Markdown test files or entire directories:

```bash
# Run all tests in tests/
md-e2e run tests/

# Run a specific test file
md-e2e run tests/checkout.test.md
```

### Command-Line Options

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `path` | Argument | *(required)* | Path to Markdown test file or test directory |
| `--headed` | Flag | `False` | Launch browser with a visible window |
| `--browser` | Choice | `chromium` | Browser engine (`chromium`, `firefox`, `webkit`) |
| `--slowmo` | Integer | `0` | Delay between actions in milliseconds |
| `--timeout` | Integer | `30000` | Action & assertion timeout budget in milliseconds |
| `--step` | Flag | `False` | Launch the interactive step debugger |
| `--healing / --no-healing` | Flag | `True` | Toggle the automatic self-healing engine |
| `--clean-session` | Flag | `False` | Isolate variable store per scenario |
| `--verbose / -v` | Flag | `False` | Display detailed step-by-step logs and traces |
| `--llm-api-key` | String | `None` | API key for AI/LLM healing fallback |
| `--report-md` | Path | `None` | Path to export GitHub PR-ready Markdown report |
| `--report-html` | Path | `None` | Path to export interactive HTML dashboard |

---

## 🐛 Interactive Step Debugger

Step through actions in real time with visual highlights in the browser:

```bash
md-e2e run tests/sample.test.md --step
```

During step debugging, each step is highlighted on the page before execution. You can control execution from the terminal:

| Key Command | Action |
| :---: | :--- |
| `Enter` | Execute current step and advance to next |
| `r` | **Retry**: Re-execute the current step |
| `e` | **Edit**: Modify the step text in-place before executing |
| `s` | **Skip**: Skip the current step without failing |
| `q` | **Quit**: Abort the entire test session |

---

## 🎥 Browser Action Recorder (Codegen)

Interactively record user actions in a real browser session and output a clean Markdown test specification:

```bash
md-e2e record "https://example.com" -o tests/recorded.test.md
```

### Recorder Features
- Automatically captures navigation, fills, clicks, selects, and keyboard presses.
- **Privacy First**: Password inputs (`type="password"` or `autocomplete="*-password"`) are automatically redacted as `<PASSWORD>`.
- **Safe Escaping**: Properly escapes quotes, newlines, and backslashes into valid DSL syntax.

---

## ℹ️ Test Suite Inspection (`md-e2e info`)

Inspect test suites, scenarios, and associated tags without launching a browser:

```bash
md-e2e info tests/
```

Outputs a tree summary of all discovered Markdown files, scenario counts, and `@tags`.

---

## 🧪 Pytest CLI Options

When running under `pytest`, md-e2e provides native command-line flags:

```bash
# Run all tests via pytest
pytest -v

# Filter by tags
pytest -m "smoke and not slow" -v

# Pytest md-e2e options
pytest --md-headed --md-timeout 15000 --md-slowmo 200
pytest --md-report-md summary.md --md-report-html report.html
```
