"""Standalone, Zero-Dependency HTML Execution Report Generator.

Creates an interactive, beautiful HTML dashboard with scenario filtering,
search, step timelines, failure screenshots, trace download links, video player
embeds, and console error log displays.
"""

from __future__ import annotations

import datetime
import html
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .executor import SuiteResult

from .executor import StepStatus
from .healing import generate_healing_diff

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Markdown E2E Test Execution Report</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-green: #22c55e;
            --accent-red: #ef4444;
            --accent-yellow: #eab308;
            --accent-cyan: #06b6d4;
            --border-color: #334155;
            --btn-bg: #3b82f6;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            padding: 2rem;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }}
        .title {{
            font-size: 1.8rem;
            font-weight: 700;
            color: #38bdf8;
            margin: 0;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: var(--card-bg);
            padding: 1.2rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            text-align: center;
        }}
        .stat-val {{
            font-size: 2rem;
            font-weight: bold;
            margin-top: 0.2rem;
        }}
        .controls {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
            align-items: center;
        }}
        .filter-btn {{
            background: var(--card-bg);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{
            background: var(--border-color);
        }}
        .filter-btn.active {{
            background: var(--btn-bg);
            border-color: var(--btn-bg);
        }}
        .search-input {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            flex-grow: 1;
            outline: none;
        }}
        .search-input:focus {{
            border-color: #3b82f6;
        }}
        .suite-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-bottom: 1.5rem;
            overflow: hidden;
        }}
        .suite-title {{
            padding: 1rem 1.5rem;
            background: rgba(255,255,255,0.03);
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
        }}
        .scenario-item {{
            padding: 1.2rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }}
        .scenario-item:last-child {{
            border-bottom: none;
        }}
        .scenario-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .badge {{
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: bold;
            text-transform: uppercase;
            display: inline-block;
        }}
        .badge-passed {{ background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }}
        .badge-failed {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }}
        .badge-healed {{ background: rgba(6, 182, 212, 0.2); color: var(--accent-cyan); }}
        .badge-skipped {{ background: rgba(234, 179, 8, 0.2); color: var(--accent-yellow); }}
        .step-list {{
            margin-top: 1rem;
            padding-left: 1rem;
            border-left: 2px solid var(--border-color);
        }}
        .step-item {{
            margin: 0.5rem 0;
            color: var(--text-secondary);
        }}
        .step-item.passed {{ color: var(--accent-green); }}
        .step-item.failed {{ color: var(--accent-red); font-weight: bold; }}
        .step-item.healed {{ color: var(--accent-cyan); }}
        .diff-box {{
            background: #090d16;
            padding: 1rem;
            border-radius: 6px;
            font-family: monospace;
            white-space: pre-wrap;
            color: #38bdf8;
            margin-top: 1rem;
            border: 1px solid var(--border-color);
        }}
        .scenario-meta {{
            margin-top: 1rem;
            padding: 1rem;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }}
        .error-log {{
            color: var(--accent-red);
            font-family: monospace;
            background: #000;
            padding: 0.8rem;
            border-radius: 4px;
            overflow-x: auto;
            white-space: pre-wrap;
            margin: 0.5rem 0;
        }}
        .console-log {{
            font-family: monospace;
            max-height: 200px;
            overflow-y: auto;
            background: rgba(0,0,0,0.3);
            padding: 0.8rem;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }}
        .console-line {{
            margin: 0.2rem 0;
            color: var(--text-secondary);
        }}
        .console-line.error {{
            color: var(--accent-red);
        }}
        .console-line.warning {{
            color: var(--accent-yellow);
        }}
        .screenshot-container {{
            margin-top: 0.8rem;
        }}
        .screenshot-img {{
            max-width: 100%;
            max-height: 400px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            cursor: zoom-in;
        }}
        .media-link {{
            color: #38bdf8;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            margin-right: 1.5rem;
            font-weight: 500;
        }}
        .media-link:hover {{
            text-decoration: underline;
        }}
        .video-container {{
            margin-top: 0.8rem;
            max-width: 480px;
        }}
        .video-player {{
            width: 100%;
            border-radius: 4px;
            border: 1px solid var(--border-color);
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1 class="title">Markdown E2E Execution Dashboard</h1>
        <div>Generated: {timestamp}</div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div>Total Scenarios</div>
            <div class="stat-val">{total_scenarios}</div>
        </div>
        <div class="stat-card">
            <div>Passed</div>
            <div class="stat-val" style="color: var(--accent-green)">{passed_scenarios}</div>
        </div>
        <div class="stat-card">
            <div>Failed</div>
            <div class="stat-val" style="color: var(--accent-red)">{failed_scenarios}</div>
        </div>
        <div class="stat-card">
            <div>Healed Steps</div>
            <div class="stat-val" style="color: var(--accent-cyan)">{healed_steps}</div>
        </div>
        <div class="stat-card">
            <div>Total Duration</div>
            <div class="stat-val">{total_duration:.2f}s</div>
        </div>
    </div>

    <div class="controls">
        <button class="filter-btn active" onclick="filterReport('all', this)">All</button>
        <button class="filter-btn" onclick="filterReport('passed', this)">Passed</button>
        <button class="filter-btn" onclick="filterReport('failed', this)">Failed</button>
        <button class="filter-btn" onclick="filterReport('healed', this)">Healed</button>
        <input type="text" class="search-input" id="searchInput" onkeyup="searchReport()" placeholder="Search scenarios..." />
    </div>

    <div id="reportContent">
        {suites_html}
    </div>

    {diff_section_html}

    <script>
        function filterReport(type, element) {{
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            if (element) {{
                element.classList.add('active');
            }}
            
            document.querySelectorAll('.scenario-item').forEach(item => {{
                if (type === 'all') item.style.display = 'block';
                else if (type === 'passed' && item.dataset.status === 'PASSED') item.style.display = 'block';
                else if (type === 'failed' && item.dataset.status === 'FAILED') item.style.display = 'block';
                else if (type === 'healed' && item.dataset.healed === 'true') item.style.display = 'block';
                else if (type === 'skipped' && item.dataset.status === 'SKIPPED') item.style.display = 'block';
                else item.style.display = 'none';
            }});
        }}

        function searchReport() {{
            const query = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.scenario-item').forEach(item => {{
                const text = item.innerText.toLowerCase();
                item.style.display = text.includes(query) ? 'block' : 'none';
            }});
        }}
    </script>
</body>
</html>
"""


def _get_rel_url(path: Path | str | None, base_dir: Path) -> str | None:
    """Get relative URL path for report output link mapping."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return os.path.relpath(p, start=base_dir).replace("\\", "/")
    except ValueError:
        return p.as_posix()


def generate_html_report(suite_results: list[SuiteResult], output_path: Path) -> None:
    """Generate interactive standalone HTML report file."""
    total_scenarios = 0
    passed_scenarios = 0
    failed_scenarios = 0
    healed_steps = 0
    total_duration = 0.0
    all_healing_events = []

    report_dir = output_path.parent
    suites_html_list = []

    for sr in suite_results:
        if sr.healing_events:
            all_healing_events.extend(sr.healing_events)

        scenarios_html = []
        for sc in sr.scenario_results:
            total_scenarios += 1
            total_duration += sc.duration_ms
            sc_healed = any(st.healed for st in sc.step_results)

            if sc_healed:
                healed_steps += sum(1 for st in sc.step_results if st.healed)

            if sc.status == StepStatus.PASSED:
                passed_scenarios += 1
                badge_class = "badge-healed" if sc_healed else "badge-passed"
                badge_text = "PASSED (HEALED)" if sc_healed else "PASSED"
            elif sc.status == StepStatus.SKIPPED:
                badge_class = "badge-skipped"
                badge_text = "SKIPPED"
            else:
                failed_scenarios += 1
                badge_class = "badge-failed"
                badge_text = "FAILED"

            steps_html_list = []
            screenshot_section = ""
            for st in sc.step_results:
                st_class = "healed" if st.healed else st.status.value.lower()
                safe_raw_text = html.escape(st.step.raw_text)
                st_text = f"✓ {safe_raw_text}" if st.status == StepStatus.PASSED else f"✗ {safe_raw_text}"
                if st.healed:
                    st_text += " 🛡️ [Healed]"
                steps_html_list.append(f'<div class="step-item {st_class}">{st_text}</div>')

                # Screenshot capture link / visual embed
                if st.screenshot_path:
                    rel_ss = _get_rel_url(st.screenshot_path, report_dir)
                    if rel_ss:
                        safe_rel_ss = html.escape(rel_ss, quote=True)
                        screenshot_section = f"""
                        <div class="screenshot-container">
                            <div style="font-weight: 600; margin-bottom: 0.4rem;">Failure Screenshot:</div>
                            <a href="{safe_rel_ss}" target="_blank">
                                <img class="screenshot-img" src="{safe_rel_ss}" alt="Failure Screenshot" />
                            </a>
                        </div>
                        """

            meta_html_list = []

            # Trace link
            if sc.trace_path:
                rel_trace = _get_rel_url(sc.trace_path, report_dir)
                if rel_trace:
                    safe_rel_trace = html.escape(rel_trace, quote=True)
                    meta_html_list.append(
                        f'<a class="media-link" href="{safe_rel_trace}" download>📥 Download Trace File (.zip)</a>'
                    )
                    # Link to trace viewer online
                    meta_html_list.append(
                        f'<a class="media-link" href="https://trace.playwright.dev/?trace={safe_rel_trace}" target="_blank">🔍 Open Trace Viewer</a>'
                    )

            # Video recording player
            if sc.video_path:
                rel_video = _get_rel_url(sc.video_path, report_dir)
                if rel_video:
                    safe_rel_video = html.escape(rel_video, quote=True)
                    meta_html_list.append(
                        f'<a class="media-link" href="{safe_rel_video}" target="_blank">🎥 Open Video Recording</a>'
                    )
                    screenshot_section += f"""
                    <div class="video-container">
                        <div style="font-weight: 600; margin-bottom: 0.4rem;">Video Playback:</div>
                        <video class="video-player" controls>
                            <source src="{safe_rel_video}" type="video/webm">
                            Your browser does not support webm video.
                        </video>
                    </div>
                    """

            # Error block
            if sc.status == StepStatus.FAILED and sc.error:
                safe_error = html.escape(sc.error)
                meta_html_list.append(f'<div class="error-log">{safe_error}</div>')

            # Console logs block
            if sc.console_logs:
                console_lines = []
                for line in sc.console_logs:
                    line_class = "console-line"
                    if "[error]" in line.lower() or "[warning]" in line.lower():
                        line_class += " error" if "[error]" in line.lower() else " warning"
                    safe_line = html.escape(line)
                    console_lines.append(f'<div class="{line_class}">{safe_line}</div>')

                meta_html_list.append(f"""
                <details style="margin-top: 0.8rem;">
                    <summary style="cursor: pointer; font-weight: 600; color: var(--text-primary);">🖥️ Console Logs ({len(sc.console_logs)} lines)</summary>
                    <div class="console-log">
                        {"".join(console_lines)}
                    </div>
                </details>
                """)

            meta_section = ""
            if meta_html_list or screenshot_section:
                meta_section = f"""
                <div class="scenario-meta">
                    {"".join(meta_html_list)}
                    {screenshot_section}
                </div>
                """

            safe_scenario_name = html.escape(sc.name)
            scenarios_html.append(f"""
            <div class="scenario-item" data-status="{sc.status.value}" data-healed="{str(sc_healed).lower()}">
                <div class="scenario-header">
                    <span><strong>{safe_scenario_name}</strong></span>
                    <div>
                        <span class="badge {badge_class}">{badge_text}</span>
                        <span style="margin-left: 1rem; color: var(--text-secondary);">{sc.duration_ms:.1f}ms</span>
                    </div>
                </div>
                <div class="step-list">
                    {"".join(steps_html_list)}
                </div>
                {meta_section}
            </div>
            """)

        safe_suite_name = html.escape(sr.name)
        suites_html_list.append(f"""
        <div class="suite-card">
            <div class="suite-title">Suite: {safe_suite_name}</div>
            {"".join(scenarios_html)}
        </div>
        """)

    diff_section_html = ""
    if all_healing_events:
        diff_text = generate_healing_diff(all_healing_events)
        safe_diff_text = html.escape(diff_text)
        diff_section_html = f"""
        <h2>🛡️ Self-Healing Auto-Patch Suggestions (git apply compatible)</h2>
        <div class="diff-box">{safe_diff_text}</div>
        """

    html_content = _HTML_TEMPLATE.format(
        timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        total_scenarios=total_scenarios,
        passed_scenarios=passed_scenarios,
        failed_scenarios=failed_scenarios,
        healed_steps=healed_steps,
        total_duration=total_duration / 1000.0,
        suites_html="".join(suites_html_list),
        diff_section_html=diff_section_html,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
