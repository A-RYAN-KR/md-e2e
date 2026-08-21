"""Unit and integration tests for Phase 6: Living Documentation & CI/CD Reporting."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from typer.testing import CliRunner

from md_e2e.models import TestStep, ActionType, TargetType
from md_e2e import SuiteResult, ScenarioResult, StepResult, StepStatus
from md_e2e.reporting import generate_markdown_report
from md_e2e.html_reporter import generate_html_report
from md_e2e.cli import app


@pytest.fixture
def sample_suite_results() -> list[SuiteResult]:
    step1 = TestStep(
        raw_text='- Navigate to "about:blank"',
        line_number=2,
        action_type=ActionType.NAVIGATE,
    )
    step2 = TestStep(
        raw_text='- Click button "Submit"',
        line_number=3,
        action_type=ActionType.CLICK,
        target_type=TargetType.BUTTON,
        target_identifier="Submit",
    )
    
    st_res1 = StepResult(step=step1, status=StepStatus.PASSED, duration_ms=25.0)
    st_res2 = StepResult(step=step2, status=StepStatus.PASSED, duration_ms=45.0, healed=True)
    
    sc_res = ScenarioResult(
        name="Scenario 1",
        status=StepStatus.PASSED,
        step_results=[st_res1, st_res2],
        duration_ms=70.0,
    )
    
    suite_res = SuiteResult(
        name="Suite 1",
        scenario_results=[sc_res],
        duration_ms=70.0,
    )
    return [suite_res]


def test_markdown_report_generation(sample_suite_results) -> None:
    """Verify markdown summary report contains progress checkboxes and badges."""
    report = generate_markdown_report(sample_suite_results)
    
    assert "# 📊 Markdown E2E Test Execution Summary" in report
    assert "brightgreen.svg" in report
    assert "- [x] **Scenario 1**" in report
    assert "- [x] - Navigate to \"about:blank\"" in report


def test_html_report_generation(sample_suite_results, tmp_path: Path) -> None:
    """Verify HTML dashboard generates layout elements and styles."""
    report_file = tmp_path / "dashboard.html"
    generate_html_report(sample_suite_results, report_file)
    
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "Markdown E2E Execution Dashboard" in content
    assert "Suite: Suite 1" in content
    assert "Scenario 1" in content
    assert "badge-healed" in content  # Contains healed steps


def test_cli_report_generation(tmp_path: Path, test_server: str) -> None:
    """Verify CLI run command generates Markdown and HTML report files."""
    runner = CliRunner()
    
    test_file = tmp_path / "simple.test.md"
    test_file.write_text(
        f"""# Simple CLI Suite
## Scenario A
- Navigate to "{test_server}/test_app.html"
- Assert heading "Welcome to the Test App" is visible
""",
        encoding="utf-8",
    )
    
    report_md = tmp_path / "summary.md"
    report_html = tmp_path / "report.html"
    
    result = runner.invoke(
        app,
        [
            "run",
            str(test_file),
            "--report-md",
            str(report_md),
            "--report-html",
            str(report_html),
        ],
    )
    
    assert result.exit_code == 0
    assert report_md.exists()
    assert report_html.exists()
    
    md_content = report_md.read_text(encoding="utf-8")
    assert "# 📊 Markdown E2E Test Execution Summary" in md_content
    
    html_content = report_html.read_text(encoding="utf-8")
    assert "Markdown E2E Execution Dashboard" in html_content


def test_pytest_report_generation(pytester: pytest.Pytester, test_server: str) -> None:
    """Verify Pytest plugin generates Markdown and HTML reports on session completion."""
    pytester.makefile(
        ".test.md",
        sample_test=f"""# Pytest Report Suite
## Scenario B
- Navigate to "{test_server}/test_app.html"
- Assert heading "Welcome to the Test App" is visible
""",
    )
    
    report_md = "py_summary.md"
    report_html = "py_report.html"
    
    result = pytester.runpytest(
        "--md-report-md",
        report_md,
        "--md-report-html",
        report_html,
    )
    
    assert result.ret == 0
    assert os.path.exists(report_md)
    assert os.path.exists(report_html)
    
    md_content = Path(report_md).read_text(encoding="utf-8")
    assert "# 📊 Markdown E2E Test Execution Summary" in md_content
    
    html_content = Path(report_html).read_text(encoding="utf-8")
    assert "Markdown E2E Execution Dashboard" in html_content
