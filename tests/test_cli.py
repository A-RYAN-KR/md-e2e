"""Unit and integration tests for the md-e2e Typer CLI and step debugger."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from md_e2e.cli import app


@pytest.fixture
def tmp_dir():
    old_cwd = os.getcwd()
    d = tempfile.mkdtemp()
    yield Path(d)
    os.chdir(old_cwd)
    shutil.rmtree(d, ignore_errors=True)


def test_cli_init(tmp_dir) -> None:
    """Verify that the init command scaffolds files correctly in a clean folder."""
    runner = CliRunner()
    
    # Run init inside tmp_dir
    os.chdir(tmp_dir)
    result = runner.invoke(app, ["init"])
    
    assert result.exit_code == 0
    assert "Initializing E2E Markdown Test Runner structure" in result.output
    
    sample_file = tmp_dir / "tests" / "sample.test.md"
    conftest_file = tmp_dir / "tests" / "conftest.py"
    
    assert sample_file.exists()
    assert conftest_file.exists()
    
    # Verify content
    content = sample_file.read_text(encoding="utf-8")
    assert "## Basic Example Domain Scenario" in content


def test_cli_run_pass_and_fail(tmp_dir, test_server) -> None:
    """Verify cli run command exit codes for passing and failing test files."""
    runner = CliRunner()
    os.chdir(tmp_dir)

    # 1. Scaffolding passing test file
    pass_file = tmp_dir / "pass.test.md"
    pass_file.write_text(
        f"""# Pass Suite
## Success Scenario
- Navigate to "{test_server}/test_app.html"
- Assert heading "Welcome to the Test App" is visible
""",
        encoding="utf-8",
    )

    result_pass = runner.invoke(app, ["run", str(pass_file)])
    assert result_pass.exit_code == 0
    assert "PASSED" in result_pass.output

    # 2. Scaffolding failing test file
    fail_file = tmp_dir / "fail.test.md"
    fail_file.write_text(
        f"""# Fail Suite
## Failure Scenario
- Navigate to "{test_server}/test_app.html"
- Assert heading "Does Not Exist Heading" is visible
""",
        encoding="utf-8",
    )

    # Set shorter timeout for failure test
    result_fail = runner.invoke(app, ["run", str(fail_file), "--timeout", "500"])
    assert result_fail.exit_code == 1
    assert "FAILED" in result_fail.output


def test_cli_debugger_stepping(tmp_dir, test_server) -> None:
    """Verify interactive debugger control flow logic using mocked inputs."""
    runner = CliRunner()
    os.chdir(tmp_dir)

    debug_file = tmp_dir / "debug.test.md"
    debug_file.write_text(
        f"""# Debug Suite
## Debug Scenario
- Navigate to "{test_server}/test_app.html"
- Assert heading "Welcome to the Test App" is visible
""",
        encoding="utf-8",
    )

    # We mock input responses:
    # 1. Navigate to: enter (next)
    # 2. Assert heading: 's' (skip) -> prints "Skipped step"
    mock_inputs = ["", "s"]

    with patch("builtins.input", side_effect=mock_inputs):
        result = runner.invoke(app, ["run", str(debug_file), "--step"])
        assert result.exit_code == 0
        assert "Debug Step" in result.output
        assert "Skipped step" in result.output


def test_cli_record(tmp_dir) -> None:
    """Verify record command invocation with mocked record_session."""
    runner = CliRunner()
    os.chdir(tmp_dir)

    out_file = tmp_dir / "recorded.test.md"
    with patch("md_e2e.recorder.record_session") as mock_record:
        async def mock_rec(url, out_path):
            out_path.write_text("# Mocked Recording", encoding="utf-8")

        mock_record.side_effect = mock_rec
        result = runner.invoke(app, ["record", "https://example.com", "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()

