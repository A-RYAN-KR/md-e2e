"""Pytest integration plugin for md-e2e test suites.

Enables auto-discovery and running of Markdown E2E tests, command line config,
fixture injection, tags as markers, and custom failure reporting.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

import pytest

from .browser import BrowserConfig, BrowserSession
from .custom_steps import current_request
from .executor import StepStatus, _run_hook, execute_scenario
from .variables import VariableStore


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom command-line options for Markdown E2E tests."""
    group = parser.getgroup("markdown-e2e", "Markdown E2E Test Runner Options")
    group.addoption(
        "--md-headed",
        action="store_true",
        default=False,
        help="Run browser tests in headed mode (default: headless).",
    )
    group.addoption(
        "--md-browser",
        action="store",
        default="chromium",
        choices=["chromium", "firefox", "webkit"],
        help="Browser engine to use (default: chromium).",
    )
    group.addoption(
        "--md-slow-mo",
        action="store",
        type=int,
        default=0,
        help="Delay Playwright actions by milliseconds (default: 0).",
    )
    group.addoption(
        "--md-timeout",
        action="store",
        type=int,
        default=30000,
        help="Playwright action timeout in milliseconds (default: 30000).",
    )
    group.addoption(
        "--md-screenshot-dir",
        action="store",
        default=None,
        help="Directory for failure screenshots (default: disabled).",
    )
    group.addoption(
        "--md-trace-dir",
        action="store",
        default=None,
        help="Directory for failure traces (default: disabled).",
    )
    group.addoption(
        "--md-no-healing",
        action="store_true",
        default=False,
        help="Disable self-healing fallback engine.",
    )
    group.addoption(
        "--md-report-md",
        action="store",
        default=None,
        help="Path to save Markdown execution summary report.",
    )
    group.addoption(
        "--md-report-html",
        action="store",
        default=None,
        help="Path to save interactive HTML dashboard report.",
    )
    group.addoption(
        "--md-llm-api-key",
        action="store",
        default=None,
        help="API key for Level 2 LLM self-healing fallback.",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Initialize md-e2e suite results container on session start."""
    session.md_suite_results = {}  # type: ignore[attr-defined]



def _get_browser_config(pytest_config: pytest.Config) -> BrowserConfig:
    """Build BrowserConfig from pytest command-line option inputs."""
    return BrowserConfig(
        browser_type=pytest_config.getoption("--md-browser"),
        headless=not pytest_config.getoption("--md-headed"),
        slow_mo=pytest_config.getoption("--md-slow-mo"),
        timeout=pytest_config.getoption("--md-timeout"),
        screenshot_dir=pytest_config.getoption("--md-screenshot-dir"),
        trace_dir=pytest_config.getoption("--md-trace-dir"),
        enable_healing=not pytest_config.getoption("--md-no-healing"),
        llm_api_key=pytest_config.getoption("--md-llm-api-key"),
    )



def pytest_collect_file(
    file_path: Path,
    parent: pytest.Collector,
) -> MarkdownFile | None:
    """Intercept *.test.md, *.spec.md, or any .md file under tests/ or e2e/ directories."""
    path = Path(file_path)
    if "fixtures" in path.parts:
        return None
    if path.name.lower() in ("readme.md", "changelog.md", "contributing.md", "license.md", "summary.md"):
        return None
    is_test_pattern = (
        path.suffix == ".md"
        and (
            path.name.endswith(".test.md")
            or path.name.endswith(".spec.md")
            or "tests" in path.parts
            or "e2e" in path.parts
        )
    )
    if is_test_pattern:
        return MarkdownFile.from_parent(parent, path=path)
    return None


class MarkdownScenarioError(Exception):
    """Custom exception raised when a Markdown scenario test step fails."""

    def __init__(
        self,
        scenario_name: str,
        failed_step: Any | None,
        error_message: str,
        screenshot_path: Path | None,
    ):
        self.scenario_name = scenario_name
        self.failed_step = failed_step
        self.error_message = error_message
        self.screenshot_path = screenshot_path
        super().__init__(error_message)


class MarkdownFile(pytest.File):
    """Collector representing a single Markdown test suite file."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suite = None
        self.suite_store = VariableStore()
        self.suite_cache = None
        self.setup_run = False
        self.total_tests = 0
        self.completed_tests = 0
        self.lock = threading.Lock()
        self.setup_success = False
        self.setup_error = None
        self.teardown_run = False
        self._temp_state_file: str | None = None
        self._browser_session: BrowserSession | None = None
        self._browser_config: BrowserConfig | None = None

    def collect(self) -> list[MarkdownScenarioItem]:
        from .md_parser import parse_markdown_file

        try:
            self.suite, _ = parse_markdown_file(self.path)
        except Exception:
            # Gracefully handle file read or parsing errors by yielding nothing
            return []

        if not self.suite or not self.suite.test_cases:
            return []

        items: list[tuple[Any, int | None, dict[str, str] | None]] = []
        for test_case in self.suite.test_cases:
            if test_case.parameters:
                for row_idx, params in enumerate(test_case.parameters):
                    items.append((test_case, row_idx, params))
            else:
                items.append((test_case, None, None))

        self.total_tests = len(items)
        collected_items = []

        if not hasattr(self.session, "_md_files"):
            self.session._md_files = []  # type: ignore[attr-defined]
        if self not in self.session._md_files:  # type: ignore[attr-defined]
            self.session._md_files.append(self)  # type: ignore[attr-defined]

        for test_case, case_row_idx, params in items:
            name = test_case.name
            if case_row_idx is not None and params:
                param_str = ", ".join(f"{k}={v}" for k, v in params.items())
                name = f"{test_case.name} [row {case_row_idx + 1}: {param_str}]"

            item = MarkdownScenarioItem.from_parent(
                self,
                name=name,
                callobj=_dummy_run,
                test_case=test_case,
                row_idx=case_row_idx,
                params=params,
            )
            collected_items.append(item)

        return collected_items

    async def ensure_suite_setup(self, config: BrowserConfig) -> None:
        """Run suite-level setup hook exactly once per file.

        Persists storage state (cookies/localStorage) from the setup context
        so subsequent scenario contexts inherit the authenticated session.
        """
        with self.lock:
            if self.setup_run:
                if self.setup_error:
                    raise self.setup_error
                return
            self.setup_run = True

        if self.suite and self.suite.suite_setup_code:
            try:
                async with BrowserSession(config) as session:
                    async with session.new_context() as (setup_ctx, page):
                        await _run_hook(
                            self.suite.suite_setup_code,
                            page,
                            self.suite_store,
                            config,
                        )
                        # Persist storage state so scenario contexts inherit
                        # cookies/localStorage set during suite setup.
                        with tempfile.NamedTemporaryFile(
                            suffix=".json", delete=False
                        ) as tf:
                            self._temp_state_file = tf.name
                        await setup_ctx.storage_state(path=self._temp_state_file)
                self.setup_success = True
            except Exception as e:
                self.setup_error = e
                raise

    async def ensure_suite_teardown(self, config: BrowserConfig) -> None:
        """Run suite-level teardown hook exactly once after all tests complete."""
        with self.lock:
            if self.teardown_run:
                return
            self.teardown_run = True

        try:
            if self.suite and self.suite.suite_teardown_code:
                async with BrowserSession(config) as session:
                    async with session.new_context() as (_ctx, page):
                        await _run_hook(
                            self.suite.suite_teardown_code,
                            page,
                            self.suite_store,
                            config,
                        )
        except Exception as e:
            logger.error(f"Error in pytest suite teardown hook: {e}")
        finally:
            # Clean up temporary state file
            if self._temp_state_file and os.path.exists(self._temp_state_file):
                try:
                    os.remove(self._temp_state_file)
                except OSError:
                    pass
            self._temp_state_file = None


def _dummy_run():
    pass


class MarkdownScenarioItem(pytest.Function):
    """Test Item representing an execution run of a Markdown Scenario."""

    def __init__(
        self,
        name: str,
        parent: MarkdownFile,
        callobj: Any,
        test_case: Any,
        row_idx: int | None,
        params: dict[str, str] | None,
        **kwargs
    ):
        super().__init__(name=name, parent=parent, callobj=callobj, **kwargs)
        self.test_case = test_case
        self.row_idx = row_idx  # type: ignore[assignment]
        self.params = params

        # Inject scenario and suite tags as pytest markers programmatically
        tags = set(test_case.tags)
        if parent.suite:
            tags.update(parent.suite.tags)

        for tag in tags:
            self.add_marker(tag)

    @property
    def parent_file(self) -> MarkdownFile:
        assert isinstance(self.parent, MarkdownFile)
        return self.parent

    def runtest(self) -> None:
        """Execute the Markdown test scenario inside an isolated event loop."""
        config = _get_browser_config(self.config)

        # Setup HealingCache lazily
        from .healing import HealingCache
        if not hasattr(self.parent_file, "suite_cache"):
            self.parent_file.suite_cache = HealingCache(config.healing_cache_path or ".md_e2e_cache.json")

        async def _run():
            # Register current pytest request in ContextVar for fixture resolving
            token = current_request.set(self._request)
            try:
                # 1. Run suite setup
                await self.parent_file.ensure_suite_setup(config)

                # 2. Copy case and isolate store (inheriting suite setup variables)
                case_store = self.parent_file.suite_store.merge({})
                tc = copy.copy(self.test_case)
                tc.steps = [copy.deepcopy(s) for s in self.test_case.steps]
                if self.params is not None:
                    tc.parameters = [self.params]

                # 3. Apply persisted storage state from suite setup
                run_config = config
                if self.parent_file._temp_state_file:
                    run_config = copy.copy(config)
                    run_config.storage_state = self.parent_file._temp_state_file

                # 4. Execute scenario
                async with BrowserSession(run_config) as session:
                    enable_trace = run_config.trace_dir is not None
                    ctx_mgr = session.new_context(trace=enable_trace)
                    async with ctx_mgr as (_ctx, page):
                        results = await execute_scenario(
                            tc, page, case_store, run_config,
                            suite_name=self.parent_file.suite.name,
                            file_path=self.path,
                            cache=self.parent_file.suite_cache,
                            base_row_idx=self.row_idx or 0,
                        )
                        result = results[0]

                        # Commit stored variables back to suite store if clean_session=False and not a matrix row
                        if not config.clean_session and self.params is None:
                            case_store.commit_to(self.parent_file.suite_store)

                        # Accumulate results in pytest session for report generation
                        from .executor import SuiteResult
                        suite_name = self.parent_file.suite.name
                        if suite_name not in self.session.md_suite_results: # type: ignore[attr-defined]
                            self.session.md_suite_results[suite_name] = SuiteResult( # type: ignore[attr-defined]
                                name=suite_name,
                            )
                        suite_result = self.session.md_suite_results[suite_name] # type: ignore[attr-defined]
                        suite_result.scenario_results.append(result)
                        if result.healing_events:
                            suite_result.healing_events.extend(result.healing_events)

                        if result.status == StepStatus.FAILED:
                            # Save trace if enabled
                            if enable_trace:
                                safe_name = re.sub(r"[^\w\-.]", "_", self.name)
                                trace_path = await ctx_mgr.save_trace(safe_name)
                                result.trace_path = trace_path

                            # Find failed step info
                            failed_step = None
                            screenshot_path = None
                            for sr in result.step_results:
                                if sr.status == StepStatus.FAILED:
                                    failed_step = sr.step
                                    screenshot_path = sr.screenshot_path
                                    break

                            raise MarkdownScenarioError(
                                scenario_name=self.name,
                                failed_step=failed_step,
                                error_message=result.error or "Scenario step failed",
                                screenshot_path=screenshot_path,
                            )
            finally:
                current_request.reset(token)

        try:
            asyncio.run(_run())
        finally:
            # Track test completion and run suite teardown if last test
            with self.parent_file.lock:
                self.parent_file.completed_tests += 1
                is_last_test = (
                    self.parent_file.completed_tests == self.parent_file.total_tests
                )

            if is_last_test:
                asyncio.run(self.parent_file.ensure_suite_teardown(config))

    def repr_failure(
        self,
        excinfo: pytest.ExceptionInfo[BaseException],
        style: str | None = None,
    ) -> Any:
        """Display cleaner, structured test failures for Markdown Scenario errors."""
        if isinstance(excinfo.value, MarkdownScenarioError):
            failed_step = excinfo.value.failed_step
            err_msg = excinfo.value.error_message
            ss = excinfo.value.screenshot_path

            line_info = f":{failed_step.line_number}" if failed_step else ""
            step_text = (
                failed_step.raw_text if failed_step else "Setup/Teardown Hook"
            )

            return (
                f"\nMarkdown E2E Failure:\n"
                f"  File: {self.path}{line_info}\n"
                f"  Step: {step_text}\n"
                f"  Error: {err_msg}\n"
                f"  Screenshot: {ss or 'None'}\n"
            )
        return super().repr_failure(excinfo)

    def reportinfo(self) -> tuple[Path, int, str]:
        """Align test reporting back to the Markdown file and heading line."""
        return (
            self.path,
            self.test_case.line_number - 1,
            f"[markdown] {self.name}",
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Ensure suite teardowns run and generate Markdown and HTML reports on session completion."""
    for md_file in getattr(session, "_md_files", []):
        if not md_file.teardown_run:
            asyncio.run(md_file.ensure_suite_teardown(md_file._browser_config or BrowserConfig()))

    report_md = session.config.getoption("--md-report-md")
    report_html = session.config.getoption("--md-report-html")
    
    suite_results = list(getattr(session, "md_suite_results", {}).values())
    if not suite_results:
        return

    if report_md:
        from .reporting import generate_markdown_report
        md_content = generate_markdown_report(suite_results)
        Path(report_md).write_text(md_content, encoding="utf-8")

    if report_html:
        from .html_reporter import generate_html_report
        generate_html_report(suite_results, Path(report_html))

