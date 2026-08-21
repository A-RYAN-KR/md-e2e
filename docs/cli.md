# Standalone CLI Command Reference

md-e2e comes with a standalone Command Line Interface tool `md-e2e`.

## Scaffold New Tests
Initialize the standard folder structure and configuration:

```bash
md-e2e init
```

This creates:
- `tests/sample.test.md`: A sample test specification.
- `tests/conftest.py`: Configuration file for custom steps.

## Execute Tests
Run test suites using the `run` command:

```bash
md-e2e run tests/
```

### Options
- `--headed`: Run browser tests in headed mode (default: headless).
- `--browser [chromium|firefox|webkit]`: Specify browser engine.
- `--slowmo <ms>`: Delay actions by milliseconds (for visual monitoring).
- `--timeout <ms>`: Action and assertion timeout threshold.
- `--step`: Enable the Interactive Step Debugger.
- `--healing / --no-healing`: Toggle the Self-Healing Engine.
- `--report-md <file>`: Output path for Markdown summary report.
- `--report-html <file>`: Output path for interactive HTML dashboard.

## Recording Interactive Sessions
Record browser actions in real-time and output to a test spec file:

```bash
md-e2e record "https://example.com" -o tests/recorded.test.md
```
