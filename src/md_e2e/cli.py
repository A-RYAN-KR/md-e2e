"""Standalone CLI Tool for md-e2e test automation framework."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import sys
from pathlib import Path
from typing import Literal, cast

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from .browser import BrowserConfig
from .executor import StepStatus, SuiteResult, execute_suite
from .md_parser import parse_markdown_file

app = typer.Typer(help="md-e2e E2E Test Automation Command Line Tool")


# ---------------------------------------------------------------------------
# Windows UTF-8 stdout safety wrapper
# ---------------------------------------------------------------------------

def _ensure_utf8_stdout() -> None:
    """Wrap sys.stdout/stderr in UTF-8 if on Windows with a non-UTF-8 codepage.

    This prevents UnicodeEncodeError when Rich prints Unicode symbols
    (→, ✓, 🛡️, 🔥) to cp1252 terminals.
    """
    if sys.platform == "win32":
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            if hasattr(stream, "encoding") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                try:
                    if hasattr(stream, "reconfigure"):
                        stream.reconfigure(encoding="utf-8", errors="replace")
                    else:
                        wrapped = io.TextIOWrapper(
                            stream.buffer,
                            encoding="utf-8",
                            errors="replace",
                            line_buffering=stream.line_buffering,
                        )
                        setattr(sys, stream_name, wrapped)
                except Exception:
                    pass  # If wrapping fails, fall through to Rich's own handling


def _safe_console() -> Console:
    """Create a Rich Console that is safe for the current terminal."""
    _ensure_utf8_stdout()
    return Console(file=sys.stdout, highlight=False)


# ---------------------------------------------------------------------------
# conftest.py auto-discovery & loading
# ---------------------------------------------------------------------------

def _load_conftest_files(test_path: Path) -> list[Path]:
    """Discover and import conftest.py files so @custom_step registrations are active.

    Scans the test directory (and parents up to test_path) for conftest.py
    files and dynamically imports them via importlib.
    """
    loaded: list[Path] = []

    if test_path.is_file():
        search_root = test_path.parent
    else:
        search_root = test_path

    # Ensure the search root's parent is on sys.path so relative imports work
    parent = str(search_root.parent.resolve())
    if parent not in sys.path:
        sys.path.insert(0, parent)

    # Also ensure CWD is on sys.path
    cwd = str(Path.cwd().resolve())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Find all conftest.py files
    conftest_files: list[Path] = []
    if search_root.is_dir():
        for p in search_root.rglob("conftest.py"):
            conftest_files.append(p)
    # Also check for conftest.py in the immediate directory if path is a file
    if test_path.is_file():
        candidate = test_path.parent / "conftest.py"
        if candidate.exists() and candidate not in conftest_files:
            conftest_files.append(candidate)

    for conftest_path in sorted(conftest_files):
        try:
            resolved = conftest_path.resolve()
            module_name = f"_md_e2e_conftest_{resolved.stem}_{hash(str(resolved)) & 0xFFFFFFFF:08x}"
            spec = importlib.util.spec_from_file_location(module_name, str(resolved))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                loaded.append(conftest_path)
                rprint(f"[dim]Loaded conftest: {conftest_path}[/dim]")
        except Exception as e:
            rprint(f"[yellow]Warning: Failed to load {conftest_path}: {e}[/yellow]")

    return loaded


# ---------------------------------------------------------------------------
# Error message formatting
# ---------------------------------------------------------------------------

_MAX_ERROR_TABLE_LEN = 200
_MAX_ERROR_DETAIL_LEN = 2000

# Patterns that indicate Playwright verbose call log noise
_PLAYWRIGHT_NOISE_MARKERS = [
    "Call log:",
    "waiting for locator(",
    "============ logs ============",
    "Locator resolved to",
    "  - ",
    "attempting click action",
    "attempting fill action",
]


def _format_step_error(error_str: str, verbose: bool = False) -> str:
    """Clean up step error messages for display.

    Strips Playwright call logs and internal tracebacks, keeping only the
    core error type and message. In verbose mode, returns the full error.
    """
    if verbose or not error_str:
        return error_str

    lines = error_str.split("\n")
    # Find where Playwright call log noise starts
    clean_lines: list[str] = []
    in_call_log = False
    for line in lines:
        stripped = line.strip()
        if any(marker in stripped for marker in _PLAYWRIGHT_NOISE_MARKERS):
            in_call_log = True
            continue
        if in_call_log and stripped.startswith("- "):
            continue
        if not stripped:
            in_call_log = False
        if not in_call_log:
            clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    if len(result) > _MAX_ERROR_DETAIL_LEN:
        result = result[:_MAX_ERROR_DETAIL_LEN] + "... [truncated]"
    return result


def _truncate_for_table(text: str) -> str:
    """Truncate error text for display in the summary table."""
    # Take first line only, and truncate
    first_line = text.split("\n")[0].strip()
    if len(first_line) > _MAX_ERROR_TABLE_LEN:
        return first_line[:_MAX_ERROR_TABLE_LEN] + "..."
    return first_line


# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

def print_results_table(suite_results: list[SuiteResult], verbose: bool = False) -> bool:
    """Print E2E test run outcomes in a beautiful Rich summary table."""
    console = _safe_console()
    table = Table(
        title="Markdown E2E Test Execution Summary",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Suite", style="dim")
    table.add_column("Scenario")
    table.add_column("Duration (ms)", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Error")

    has_failures = False
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_duration = 0.0
    all_healing_events = []

    for sr in suite_results:
        if sr.healing_events:
            all_healing_events.extend(sr.healing_events)
        for sc in sr.scenario_results:
            duration = f"{sc.duration_ms:.1f}"
            total_duration += sc.duration_ms

            if sc.status == StepStatus.PASSED:
                status_str = "[cyan]PASSED (HEALED)[/cyan]" if any(st.healed for st in sc.step_results) else "[green]PASSED[/green]"
                error_str = ""
                total_passed += 1
            elif sc.status == StepStatus.SKIPPED:
                status_str = "[yellow]SKIPPED[/yellow]"
                error_str = ""
                total_skipped += 1
            else:
                status_str = "[red]FAILED[/red]"
                raw_error = sc.error or "Unknown failure"
                error_str = _truncate_for_table(_format_step_error(raw_error, verbose=verbose))
                total_failed += 1
                has_failures = True

            table.add_row(sr.name, sc.name, duration, status_str, error_str)

    console.print(table)
    total_tests = total_passed + total_failed + total_skipped
    skip_summary = f", {total_skipped} skipped" if total_skipped else ""
    rprint(
        f"\n[bold]Totals:[/bold] {total_tests} scenarios "
        f"({total_passed} passed, {total_failed} failed{skip_summary}) in {total_duration / 1000:.2f}s"
    )

    # Print detailed failure info with formatted errors
    if has_failures and not verbose:
        rprint("\n[dim]Tip: Use --verbose for full error traces[/dim]")

    if all_healing_events:
        from .healing import generate_healing_diff
        diff = generate_healing_diff(all_healing_events)
        rprint("\n[bold cyan]Self-Healing Patch Suggestions (git apply compatible):[/bold cyan]")
        rprint(f"[dim]{diff}[/dim]\n")

    return has_failures



def find_test_files(path: Path) -> list[Path]:
    """Find all markdown test specs recursively under path."""
    if path.is_file():
        return [path]

    files = []
    for p in path.rglob("*.md"):
        if "fixtures" in p.parts:
            continue
        if p.name.lower() in ("readme.md", "changelog.md", "contributing.md", "license.md", "summary.md"):
            continue
        is_test = (
            p.name.endswith(".test.md")
            or p.name.endswith(".spec.md")
            or "tests" in p.parts
            or "e2e" in p.parts
        )
        if is_test:
            files.append(p)
    return files


@app.command()
def init() -> None:
    """Scaffold a basic E2E testing folder structure and sample files."""
    rprint("[bold blue]Initializing E2E Markdown Test Runner structure...[/bold blue]")

    tests_dir = Path("tests")
    tests_dir.mkdir(exist_ok=True)

    sample_test = tests_dir / "sample.test.md"
    conftest_file = tests_dir / "conftest.py"

    # Write sample E2E spec
    if not sample_test.exists():
        sample_test.write_text(
            """# Sample E2E Test Suite

This is an automatically generated sample E2E Markdown specification.

## Basic Example Domain Scenario
- Navigate to "https://example.com"
- Assert heading "Example Domain" is visible
""",
            encoding="utf-8",
        )
        rprint(f"[green]Scaffolded sample test file:[/green] {sample_test}")
    else:
        rprint(f"[yellow]Test file already exists, skipping:[/yellow] {sample_test}")

    # Write sample conftest.py
    if not conftest_file.exists():
        conftest_file.write_text(
            """# conftest.py - Scaffolding for E2E custom steps and fixtures
from md_e2e import custom_step

# Add custom steps below, for example:
# @custom_step(r'Click the custom link')
# async def click_custom(page):
#     await page.click('.custom-link')
""",
            encoding="utf-8",
        )
        rprint(f"[green]Scaffolded conftest configuration file:[/green] {conftest_file}")
    else:
        rprint(f"[yellow]conftest.py already exists, skipping:[/yellow] {conftest_file}")

    rprint("\n[bold green]Successfully initialized! Run tests using: md-e2e run tests/[/bold green]")


@app.command()
def run(
    path: Path = typer.Argument(..., help="Path to markdown test file or directory of test suites."),
    headed: bool = typer.Option(False, "--headed", help="Run browser tests in headed mode."),
    browser: str = typer.Option("chromium", "--browser", help="Playwright browser engine (chromium, firefox, webkit)."),
    slowmo: int = typer.Option(0, "--slowmo", help="Action delay slow-mo in milliseconds."),
    timeout: int = typer.Option(30000, "--timeout", help="Default assertion/action timeout in milliseconds."),
    step: bool = typer.Option(False, "--step", help="Enable interactive step-by-step debugger."),
    healing: bool = typer.Option(True, "--healing/--no-healing", help="Enable/disable self-healing engine."),
    report_md: Path | None = typer.Option(None, "--report-md", help="Output path for Markdown summary report (e.g. summary.md)."),
    report_html: Path | None = typer.Option(None, "--report-html", help="Output path for interactive HTML dashboard (e.g. report.html)."),
    llm_api_key: str | None = typer.Option(None, "--llm-api-key", help="API key for Level 2 LLM self-healing fallback (e.g. OpenAI / OpenRouter)."),
    clean_session: bool = typer.Option(False, "--clean-session", help="Isolate browser context and variables per scenario (no state bleed)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full error traces including Playwright call logs."),
) -> None:
    """Execute Markdown E2E test suites found at the path."""
    # Load conftest.py files BEFORE finding/executing tests
    _load_conftest_files(path)

    test_files = find_test_files(path)
    if not test_files:
        rprint(f"[red]Error: No Markdown E2E tests found at path: {path}[/red]")
        raise typer.Exit(code=1)

    # Chromium engine mapping for chrome
    browser_engine = "chromium" if browser == "chrome" else browser

    config = BrowserConfig(
        browser_type=cast(Literal["chromium", "firefox", "webkit"], browser_engine),
        headless=not headed,
        slow_mo=slowmo,
        timeout=timeout,
        enable_healing=healing,
        llm_api_key=llm_api_key,
        clean_session=clean_session,
    )

    suite_results: list[SuiteResult] = []
    has_execution_error = False

    async def _execute_all():
        nonlocal has_execution_error
        for f in test_files:
            try:
                suite, errors = parse_markdown_file(f)
                if errors:
                    rprint(f"[yellow]Warnings parsing {f.name}:[/yellow]")
                    for err in errors:
                        rprint(f"  - Line {err.line_number}: {err.message}")

                if not suite.test_cases:
                    continue

                res = await execute_suite(suite, config, step_debug=step)
                suite_results.append(res)
            except Exception as e:
                has_execution_error = True
                rprint(f"[red]Error executing suite {f.name}: {e}[/red]")

    asyncio.run(_execute_all())

    # Save reports if requested
    if report_md:
        from .reporting import generate_markdown_report
        md_content = generate_markdown_report(suite_results)
        report_md.write_text(md_content, encoding="utf-8")
        rprint(f"[bold green]Saved Markdown summary report to:[/bold green] {report_md}")

    if report_html:
        from .html_reporter import generate_html_report
        generate_html_report(suite_results, report_html)
        rprint(f"[bold green]Saved HTML dashboard report to:[/bold green] {report_html}")

    # Print pretty Rich outcomes summary table
    has_failures = print_results_table(suite_results, verbose=verbose) or has_execution_error

    if has_failures:
        raise typer.Exit(code=1)
    else:
        raise typer.Exit(code=0)



@app.command()
def record(
    url: str = typer.Argument(..., help="Starting URL to record the E2E session."),
    output: Path = typer.Option(Path("recorded.test.md"), "-o", "--output", help="Output path for recorded markdown test file."),
) -> None:
    """Launch an interactive headed browser to record actions and output an E2E Markdown file."""
    from .recorder import record_session
    try:
        asyncio.run(record_session(url, output))
    except Exception as e:
        rprint(f"[red]Error during recording session: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def info(
    path: Path = typer.Argument(..., help="Path to markdown test file to inspect."),
) -> None:
    """Inspect and display metadata/scenarios for a Markdown E2E test file."""
    if not path.exists():
        rprint(f"[red]Error: File not found: {path}[/red]")
        raise typer.Exit(code=1)

    suite, errors = parse_markdown_file(path)
    rprint(f"[bold cyan]Suite:[/bold cyan] {suite.name}")
    if suite.tags:
        rprint(f"[bold magenta]Tags:[/bold magenta] {' '.join(suite.tags)}")
    rprint(f"[bold yellow]Scenarios ({len(suite.test_cases)}):[/bold yellow]")
    for sc in suite.test_cases:
        rprint(f"  • {sc.name} ({len(sc.steps)} steps)")


if __name__ == "__main__":
    app()
