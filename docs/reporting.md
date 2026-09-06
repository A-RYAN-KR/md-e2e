# Living Documentation & CI/CD Reports

md-e2e treats test specifications as living documentation. In addition to console outputs, it generates comprehensive reports for team communication, pull request reviews, and CI/CD pipelines.

---

## 📄 GitHub PR Markdown Summary (`--report-md`)

Generate a clean, GitHub-flavored Markdown report ideal for automated PR comments or `$GITHUB_STEP_SUMMARY`:

```bash
md-e2e run tests/ --report-md summary.md
```

### Report Contents
- **Suite Outcome Badges**: Clear visual badges for Total, Passed, Failed, and Healed scenario counts.
- **Progress Checklists**:
  - `- [x]` Passed steps with execution timestamps
  - `- [ ] ❌` Failed steps with highlighted error messages
  - `- [ ] ⚠️` Skipped steps
- **Collapsible Failure Details**: `<details>` blocks containing failure traces and inline screenshots.
- **Self-Healing Summary**: Unified diff view showing original vs healed selectors.

---

## 📊 Interactive HTML Dashboard (`--report-html`)

Generate a standalone, zero-dependency HTML dashboard for test artifact archiving:

```bash
md-e2e run tests/ --report-html report.html
```

### Dashboard Features
- **Filterable Views**: One-click filtering by test status (`All`, `Passed`, `Failed`, `Healed`).
- **Instant Search**: Instant client-side search across suites, scenarios, and step text.
- **Visual Timeline**: Accurate per-step execution durations to identify slow operations.
- **Embedded Media**:
  - Inline failure screenshots taken at the exact moment of failure.
  - Embedded HTML5 video recordings of the browser session.
  - Direct download links for Playwright trace files (`.zip`) compatible with [trace.playwright.dev](https://trace.playwright.dev).

---

## 🤖 CI/CD Integration

### GitHub Actions Workflow (`.github/workflows/e2e.yml`)

Integrate md-e2e into your GitHub Actions workflow with PR summary reporting and artifact archiving:

```yaml
name: End-to-End Tests
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Dependencies
        run: |
          pip install md-e2e
          playwright install --with-deps chromium

      - name: Run md-e2e Test Suites
        run: |
          md-e2e run tests/ \
            --report-md summary.md \
            --report-html report.html
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      - name: Publish Test Summary to Job
        if: always()
        run: cat summary.md >> $GITHUB_STEP_SUMMARY

      - name: Upload HTML Dashboard Artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-html-report
          path: report.html
```

---

## 🧪 Generating Reports under Pytest

You can also generate both reports when executing via `pytest`:

```bash
pytest --md-report-md summary.md --md-report-html report.html
```
