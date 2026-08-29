"""Markdown-Native Living Documentation & Summary Report Generator.

Generates GitHub PR comment-compatible Markdown summaries containing status
badges, checkbox progress lists, collapsible error callouts with stack traces,
and self-healing git apply patch diffs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .executor import SuiteResult

from pathlib import Path

from .executor import StepStatus
from .healing import generate_healing_diff


def _escape_md_cell(text: str) -> str:
    """Escape vertical pipe characters in markdown table cells."""
    return text.replace("|", "\\|")


def generate_markdown_report(suite_results: list[SuiteResult]) -> str:
    """Generate Markdown report content suitable for PR comments or documentation."""
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_healed = 0
    total_duration = 0.0
    all_healing_events = []

    for sr in suite_results:
        if sr.healing_events:
            all_healing_events.extend(sr.healing_events)
        for sc in sr.scenario_results:
            total_duration += sc.duration_ms
            if sc.status == StepStatus.PASSED:
                total_passed += 1
                if any(st.healed for st in sc.step_results):
                    total_healed += 1
            elif sc.status == StepStatus.SKIPPED:
                total_skipped += 1
            else:
                total_failed += 1

    total_tests = total_passed + total_failed + total_skipped
    has_failures = total_failed > 0

    status_badge = (
        "![Status: Failed](https://img.shields.io/badge/Status-FAILED-red.svg)"
        if has_failures
        else "![Status: Passed](https://img.shields.io/badge/Status-PASSED-brightgreen.svg)"
    )

    lines: list[str] = [
        "# 📊 Markdown E2E Test Execution Summary",
        "",
        f"{status_badge} **`{total_passed}/{total_tests}` Scenarios Passed** in `{total_duration / 1000:.2f}s`",
        "",
        "| Suite | Total | Passed | Failed | Healed | Duration |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for sr in suite_results:
        passed = sum(1 for sc in sr.scenario_results if sc.status == StepStatus.PASSED)
        failed = sum(1 for sc in sr.scenario_results if sc.status == StepStatus.FAILED)
        healed = sum(1 for sc in sr.scenario_results if any(st.healed for st in sc.step_results))
        dur = sum(sc.duration_ms for sc in sr.scenario_results)
        safe_name = _escape_md_cell(sr.name)
        lines.append(f"| `{safe_name}` | {len(sr.scenario_results)} | {passed} | {failed} | {healed} | {dur / 1000:.2f}s |")

    lines.append("")
    lines.append("## 📋 Scenario Execution Details")
    lines.append("")

    for sr in suite_results:
        lines.append(f"### 📂 Suite: `{sr.name}`")
        for sc in sr.scenario_results:
            sc_healed = any(st.healed for st in sc.step_results)
            if sc.status == StepStatus.PASSED:
                status_tag = " [HEALED]" if sc_healed else ""
                lines.append(f"- [x] **{sc.name}** (`{sc.duration_ms:.1f}ms`){status_tag}")
            elif sc.status == StepStatus.SKIPPED:
                lines.append(f"- [ ] ⚠️ **{sc.name}** (SKIPPED)")
            else:
                lines.append(f"- [ ] ❌ **{sc.name}** (`{sc.duration_ms:.1f}ms`) — `FAILED`")

            # List individual steps
            for st in sc.step_results:
                if st.status == StepStatus.PASSED:
                    heal_mark = " 🛡️ *(Healed)*" if st.healed else ""
                    lines.append(f"  - [x] {st.step.raw_text}{heal_mark}")
                elif st.status == StepStatus.SKIPPED:
                    lines.append(f"  - [ ] ⚠️ {st.step.raw_text}")
                else:
                    lines.append(f"  - [ ] ❌ **{st.step.raw_text}** (line {st.step.line_number})")

            # Add collapsible error details if scenario failed
            if sc.status == StepStatus.FAILED and sc.error:
                lines.append("")
                lines.append("  <details>")
                lines.append("  <summary>🔍 <b>View Failure Traceback & Error Details</b></summary>")
                lines.append("")
                lines.append("  ```text")
                lines.append(f"  {sc.error}")
                lines.append("  ```")
                failed_step = next((s for s in sc.step_results if s.status == StepStatus.FAILED), None)
                if failed_step and failed_step.screenshot_path:
                    posix_path = Path(failed_step.screenshot_path).as_posix()
                    lines.append(f"  ![Screenshot](file:///{posix_path})")
                lines.append("  </details>")
                lines.append("")

    # Add Self-Healing Section if events occurred
    if all_healing_events:
        diff = generate_healing_diff(all_healing_events)
        lines.append("## 🛡️ Self-Healing Auto-Patch Suggestions")
        lines.append("The following spec updates were healed automatically during execution:")
        lines.append("")
        lines.append("```diff")
        lines.append(diff)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)
