"""Unit tests for codegen recorder (recorder.py)."""

from __future__ import annotations

from pathlib import Path
from md_e2e.recorder import format_action_to_dsl, generate_markdown_spec


def test_format_action_to_dsl() -> None:
    """Test formatting recorded action dictionaries into Markdown DSL strings."""
    nav_step = format_action_to_dsl({"action": "NAVIGATE", "url": "https://example.com"})
    assert nav_step == '- Navigate to "https://example.com"'

    link_step = format_action_to_dsl({"action": "CLICK_LINK", "target": "More Information"})
    assert link_step == '- Click link "More Information"'

    btn_step = format_action_to_dsl({"action": "CLICK_BUTTON", "target": "Submit Form"})
    assert btn_step == '- Click button "Submit Form"'

    fill_step = format_action_to_dsl({"action": "FILL", "target": "Email", "value": "test@example.com"})
    assert fill_step == '- Fill input "Email" with "test@example.com"'

    select_step = format_action_to_dsl({"action": "SELECT", "target": "Country", "value": "Canada"})
    assert select_step == '- Select "Canada" from "Country"'

    check_step = format_action_to_dsl({"action": "CHECK", "target": "Terms"})
    assert check_step == '- Check checkbox "Terms"'

    uncheck_step = format_action_to_dsl({"action": "UNCHECK", "target": "Newsletter"})
    assert uncheck_step == '- Uncheck checkbox "Newsletter"'

    unknown_step = format_action_to_dsl({"action": "UNKNOWN"})
    assert unknown_step == ""


def test_generate_markdown_spec(tmp_path: Path) -> None:
    """Test markdown specification document generation."""
    steps = [
        '- Navigate to "http://localhost:8080/test_app.html"',
        '- Fill input "Email" with "user@test.com"',
        '- Click button "Submit"',
    ]
    spec = generate_markdown_spec("http://localhost:8080/test_app.html", steps)
    
    assert "# Recorded Test Suite" in spec
    assert "starting from http://localhost:8080/test_app.html" in spec
    assert '- Navigate to "http://localhost:8080/test_app.html"' in spec
    assert '- Fill input "Email" with "user@test.com"' in spec
    assert '- Click button "Submit"' in spec
