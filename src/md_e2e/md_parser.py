"""Markdown AST extractor — parses ``.md`` test specs into a TestSuite IR.

Uses ``markdown-it-py`` to tokenise GitHub-Flavoured Markdown and walks
the flat token stream to build :class:`TestSuite` → :class:`TestCase` →
:class:`TestStep` hierarchies.

Document-structure mapping
--------------------------
* ``# Title @tag1 @tag2``            → ``TestSuite.name`` / ``.tags``
* Paragraphs before first ``##``     → ``TestSuite.description``
* ````` ```python setup ``````       → suite or scenario ``setup_code``
* ````` ```python teardown ``````    → suite or scenario ``teardown_code``
* ``## Scenario @tag``               → ``TestCase.name`` / ``.tags``
* Paragraphs after ``##``            → ``TestCase.description``
* ``- step`` / ``* step``            → ``TestStep`` (passed to DSL parser)
* ``- [ ] step`` / ``- [x] step``    → checklist ``TestStep``
* Markdown tables                    → ``TestCase.parameters``

Line numbers are **1-indexed** (``markdown-it-py`` provides 0-indexed maps;
we add 1 when assigning ``line_number``).
"""

from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt

from .dsl_parser import parse_step
from .models import ParseError, TestCase, TestSuite

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TAG_PATTERN = re.compile(r"(?:^|\s)@(\w[\w-]*)")
_TAG_SUB_PATTERN = re.compile(r"(?:^|\s)@\w[\w-]*")
_CHECKLIST_PATTERN = re.compile(r"^\s*\[([ xX])\]\s+(.*)", re.DOTALL)


def _extract_tags(text: str) -> tuple[str, list[str]]:
    """Split ``@tag`` annotations from heading text.

    Requires ``@tag`` to be at the start of the string or preceded by whitespace,
    preventing email addresses (e.g. ``user@example.com``) from being corrupted.

    Returns ``(clean_name, [tags])``.
    """
    tags = _TAG_PATTERN.findall(text)
    clean = _TAG_SUB_PATTERN.sub("", text).strip()
    return clean, tags


def _token_line(token) -> int:
    """Return a **1-indexed** line number from a ``markdown-it-py`` token."""
    if token.map is not None:
        return token.map[0] + 1  # 0-indexed → 1-indexed
    return 0


def _inline_text(token) -> str:
    """Extract plain text from an ``inline`` token, collapsing children."""
    if token.children:
        return "".join(
            child.content for child in token.children if child.type in ("text", "code_inline", "softbreak")
        ).strip()
    return token.content.strip()


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------

def _parse_table_tokens(tokens: list, start_idx: int) -> tuple[list[dict[str, str]], int]:
    """Parse a Markdown table from the token stream starting at *start_idx*.

    Returns ``(rows_as_dicts, next_index_after_table)``.
    """
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    i = start_idx
    in_head = False
    in_body = False
    current_row: list[str] = []

    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "thead_open":
            in_head = True
        elif tok.type == "thead_close":
            in_head = False
        elif tok.type == "tbody_open":
            in_body = True
        elif tok.type == "tbody_close":
            in_body = False
        elif tok.type == "tr_open":
            current_row = []
        elif tok.type == "tr_close":
            if in_head:
                headers = [h.strip() for h in current_row]
            elif in_body and headers:
                row_dict = {
                    h.strip(): (current_row[col_idx].strip() if col_idx < len(current_row) else "")
                    for col_idx, h in enumerate(headers)
                }
                rows.append(row_dict)
        elif tok.type == "inline" and (in_head or in_body):
            current_row.append(_inline_text(tok))
        elif tok.type == "table_close":
            return rows, i + 1

        i += 1

    return rows, i


def _parse_pipe_table_text(text: str) -> list[dict[str, str]]:
    """Parse pipe-delimited table text when markdown-it parses it as a paragraph."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    if not all(line.startswith("|") and line.endswith("|") for line in lines):
        return []

    raw_rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip separator rows like | --- | --- |
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue
        raw_rows.append(cells)

    if len(raw_rows) < 2:
        return []

    headers = raw_rows[0]
    result_rows = []
    for row in raw_rows[1:]:
        row_dict = {
            h: (row[col_idx] if col_idx < len(row) else "")
            for col_idx, h in enumerate(headers)
        }
        result_rows.append(row_dict)
    return result_rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_markdown(
    text: str,
    *,
    file_path: Path | str | None = None,
) -> tuple[TestSuite, list[ParseError]]:
    """Parse a Markdown string into a :class:`TestSuite`.

    Parameters
    ----------
    text:
        Raw Markdown content.
    file_path:
        Optional filesystem path (attached to the suite and errors for
        identification in reports).

    Returns
    -------
    tuple[TestSuite, list[ParseError]]
        The parsed suite and a (possibly empty) list of parse warnings /
        errors.
    """
    fpath = Path(file_path) if file_path else None

    md = MarkdownIt().enable("table")
    tokens = md.parse(text)

    suite = TestSuite(name="", file_path=fpath)
    errors: list[ParseError] = []

    current_case: TestCase | None = None
    # Whether we are still before the first ## heading (suite-level context)
    in_suite_preamble = True
    # Accumulate description paragraphs
    suite_desc_parts: list[str] = []
    case_desc_parts: list[str] = []
    # Track if we have seen list items in the current case (to stop collecting description)
    case_has_steps = False

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # ── Headings ─────────────────────────────────────────────────────
        if tok.type == "heading_open":
            level = int(tok.tag[1:]) if len(tok.tag) > 1 and tok.tag[1:].isdigit() else 1
            i += 1
            heading_raw = ""
            if i < len(tokens) and tokens[i].type == "inline":
                heading_raw = _inline_text(tokens[i])

            if level == 1:
                # Suite heading
                name, tags = _extract_tags(heading_raw)
                suite.name = name
                suite.tags = tags
                suite_desc_parts = []
            elif level == 2:
                # Finalise previous case description
                if current_case is not None and case_desc_parts and current_case.description is None:
                    current_case.description = "\n\n".join(case_desc_parts)

                in_suite_preamble = False
                # Finalise suite description from preamble
                if suite_desc_parts and suite.description is None:
                    suite.description = "\n\n".join(suite_desc_parts)

                case_name, case_tags = _extract_tags(heading_raw)
                line = _token_line(tok)
                current_case = TestCase(
                    name=case_name,
                    line_number=line,
                    tags=case_tags,
                )
                suite.test_cases.append(current_case)
                case_desc_parts = []
                case_has_steps = False

            # Skip heading_close
            i += 1
            if i < len(tokens) and tokens[i].type == "heading_close":
                i += 1
            continue

        # ── Paragraph (description capture & fallback table parsing) ────
        if tok.type == "paragraph_open":
            i += 1
            if i < len(tokens) and tokens[i].type == "inline":
                para_text = _inline_text(tokens[i])
                pipe_table_rows = _parse_pipe_table_text(para_text)
                if current_case is not None and pipe_table_rows and not current_case.parameters:
                    current_case.parameters = pipe_table_rows
                else:
                    if in_suite_preamble:
                        suite_desc_parts.append(para_text)
                    elif current_case is not None and not case_has_steps:
                        case_desc_parts.append(para_text)
            # Skip paragraph_close
            i += 1
            if i < len(tokens) and tokens[i].type == "paragraph_close":
                i += 1
            continue

        # ── Fenced code block (setup / teardown hooks) ───────────────────
        if tok.type == "fence":
            info = (tok.info or "").strip().lower()
            code = tok.content
            line = _token_line(tok)

            if info == "python setup":
                if in_suite_preamble:
                    suite.suite_setup_code = code
                elif current_case is not None:
                    current_case.setup_code = code
            elif info == "python teardown":
                if in_suite_preamble:
                    suite.suite_teardown_code = code
                elif current_case is not None:
                    current_case.teardown_code = code
            # Other fenced blocks are ignored (e.g. ```js, ```bash)
            i += 1
            continue

        # ── Table (parameterised data matrix) ────────────────────────────
        if tok.type == "table_open":
            rows, next_i = _parse_table_tokens(tokens, i)
            if current_case is not None and rows:
                current_case.parameters = rows
            i = next_i
            continue

        # ── List items (test steps) ──────────────────────────────────────
        if tok.type == "list_item_open":
            if current_case is not None and case_desc_parts and current_case.description is None:
                current_case.description = "\n\n".join(case_desc_parts)
            case_has_steps = True
            # Walk forward to find the inline content of this list item
            i += 1
            item_line = _token_line(tok)
            while i < len(tokens) and tokens[i].type != "list_item_close":
                if tokens[i].type == "inline":
                    raw = _inline_text(tokens[i])
                    line = item_line or _token_line(tokens[i])

                    # Detect checklist markers
                    is_checklist = False
                    is_checked = False
                    m = _CHECKLIST_PATTERN.match(raw)
                    if m:
                        is_checklist = True
                        is_checked = m.group(1).lower() == "x"
                        raw = m.group(2).strip()

                    if current_case is not None and raw:
                        step, error = parse_step(raw, line_number=line)
                        step.is_checklist_item = is_checklist
                        step.is_checked = is_checked
                        current_case.steps.append(step)

                        if error is not None:
                            error.file_path = fpath
                            errors.append(error)
                i += 1
            # Skip list_item_close
            if i < len(tokens) and tokens[i].type == "list_item_close":
                i += 1
            continue

        # ── Everything else: skip ────────────────────────────────────────
        i += 1

    # Finalise trailing descriptions
    if suite_desc_parts and suite.description is None:
        suite.description = "\n\n".join(suite_desc_parts)
    if current_case is not None and case_desc_parts and current_case.description is None:
        current_case.description = "\n\n".join(case_desc_parts)

    # Default suite name if no h1 was found
    if not suite.name:
        if fpath:
            suite.name = fpath.stem
        else:
            suite.name = "Untitled Suite"

    return suite, errors


def parse_markdown_file(
    path: Path | str,
) -> tuple[TestSuite, list[ParseError]]:
    """Convenience wrapper that reads a file and calls :func:`parse_markdown`."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return parse_markdown(text, file_path=p)
