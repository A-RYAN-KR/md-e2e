"""DSL step parser — transforms a natural-language step string into a TestStep.

Uses a Lark grammar (``grammar.lark``) to parse the step text, then a
Transformer to build the :class:`TestStep` IR node.  Steps that do not match
the built-in grammar are returned with ``ActionType.CUSTOM`` rather than
raising an error — Phase 3's ``@step(...)`` registry can resolve them later.

Variable references (``{{var}}``, ``{{ var }}``, ``${var}``) are detected,
normalised, and recorded in ``TestStep.variables``.
"""

from __future__ import annotations

import re
from pathlib import Path

from lark import Lark, Token, Transformer, UnexpectedInput

from .models import ActionType, ParseError, TargetType, TestStep

# ---------------------------------------------------------------------------
# Grammar singleton
# ---------------------------------------------------------------------------

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"

_parser: Lark | None = None


def _get_parser() -> Lark:
    """Lazily instantiate and cache the Lark parser."""
    global _parser
    if _parser is None:
        _parser = Lark(
            _GRAMMAR_PATH.read_text(encoding="utf-8"),
            parser="earley",
            ambiguity="resolve",
        )
    return _parser


# ---------------------------------------------------------------------------
# Variable detection & normalisation
# ---------------------------------------------------------------------------

# Matches  {{ name }}  or  {{name}}  or  ${ name }  or  ${name}  or  <name>
_VAR_PATTERN = re.compile(
    r"\{\{\s*(?P<jinja>\w+)\s*\}\}"  # Jinja-style
    r"|"
    r"\$\{\s*(?P<shell>\w+)\s*\}"   # Shell-style
    r"|"
    r"<(?P<angle>\w+)>",            # Scenario outline table style
)


def _extract_variables(text: str) -> list[str]:
    """Return a de-duplicated, ordered list of variable names found in *text*."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _VAR_PATTERN.finditer(text):
        name = m.group("jinja") or m.group("shell") or m.group("angle")
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_quotes(token: Token | str) -> str:
    """Remove surrounding quote characters (double, single, backtick) and unescape internal escapes."""
    s = str(token).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        quote = s[0]
        inner = s[1:-1]
        return re.sub(r'\\([\\"' + re.escape(quote) + r'])', r'\1', inner)
    return s


def _resolve_target_type(token: Token | str) -> TargetType:
    """Map a grammar ``TARGET_TYPE`` token value to the enum."""
    mapping = {
        "button": TargetType.BUTTON,
        "link": TargetType.LINK,
        "input": TargetType.INPUT,
        "heading": TargetType.HEADING,
        "text": TargetType.TEXT,
        "checkbox": TargetType.CHECKBOX,
        "radio": TargetType.RADIO,
    }
    return mapping.get(str(token).strip().lower(), TargetType.GENERIC)


# ---------------------------------------------------------------------------
# Lark Transformer  →  TestStep
# ---------------------------------------------------------------------------

# Token types that carry semantic meaning (everything else is a keyword)
_MEANINGFUL_TYPES = frozenset({"QSTR", "TARGET_TYPE", "CMP", "NUMBER"})


def _filter_items(items) -> list[Token]:
    """Keep only semantically meaningful tokens, discarding keyword tokens."""
    return [tok for tok in items if isinstance(tok, Token) and tok.type in _MEANINGFUL_TYPES]


class _StepTransformer(Transformer):
    """Converts a Lark parse tree into a :class:`TestStep` instance.

    Each ``def rule_name(self, items)`` corresponds to a grammar rule and
    returns a partially filled ``TestStep``.  The ``raw_text`` and
    ``line_number`` are injected by the caller after transformation.

    All keyword tokens (CLICK_KW, WITH_KW, etc.) are filtered out before
    processing — only QSTR, TARGET_TYPE, CMP, and NUMBER tokens are used.
    """

    # ── Navigation ───────────────────────────────────────────────────────

    def navigate(self, items):
        meaningful = _filter_items(items)
        url = _strip_quotes(meaningful[0])
        return {"action_type": ActionType.NAVIGATE, "target_identifier": url}

    def reload(self, items):
        return {"action_type": ActionType.RELOAD}

    # ── Interaction ──────────────────────────────────────────────────────

    def click(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:  # TARGET_TYPE + QSTR
            return {
                "action_type": ActionType.CLICK,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.CLICK,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def fill(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 3:  # TARGET_TYPE + QSTR + QSTR
            return {
                "action_type": ActionType.FILL,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
                "value": _strip_quotes(meaningful[2]),
            }
        return {
            "action_type": ActionType.FILL,
            "target_identifier": _strip_quotes(meaningful[0]),
            "value": _strip_quotes(meaningful[1]),
        }

    def select_option(self, items):
        meaningful = _filter_items(items)
        # Grammar: SELECT_KW QSTR(option) FROM_KW QSTR(dropdown)
        return {
            "action_type": ActionType.SELECT,
            "target_identifier": _strip_quotes(meaningful[1]),  # dropdown
            "value": _strip_quotes(meaningful[0]),  # option to select
        }

    def hover(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:
            return {
                "action_type": ActionType.HOVER,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.HOVER,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def press_key(self, items):
        meaningful = _filter_items(items)
        return {
            "action_type": ActionType.PRESS,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def upload_file(self, items):
        meaningful = _filter_items(items)
        # Grammar: UPLOAD_KW QSTR(file) TO_KW QSTR(input)
        return {
            "action_type": ActionType.UPLOAD,
            "target_identifier": _strip_quotes(meaningful[1]),  # input element
            "value": _strip_quotes(meaningful[0]),  # file path
        }

    def check_box(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:
            return {
                "action_type": ActionType.CHECK,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.CHECK,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def uncheck_box(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:
            return {
                "action_type": ActionType.UNCHECK,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.UNCHECK,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    # ── Assertions ───────────────────────────────────────────────────────

    def assert_visible(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:  # TARGET_TYPE + QSTR
            return {
                "action_type": ActionType.ASSERT_VISIBLE,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.ASSERT_VISIBLE,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def assert_hidden(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 2:
            return {
                "action_type": ActionType.ASSERT_HIDDEN,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
            }
        return {
            "action_type": ActionType.ASSERT_HIDDEN,
            "target_identifier": _strip_quotes(meaningful[0]),
        }

    def assert_url(self, items):
        meaningful = _filter_items(items)
        # meaningful: CMP + QSTR
        cmp_mode = str(meaningful[0]).strip().lower()
        return {
            "action_type": ActionType.ASSERT_URL,
            "target_identifier": cmp_mode,
            "value": _strip_quotes(meaningful[1]),
        }

    def assert_title(self, items):
        meaningful = _filter_items(items)
        cmp_mode = str(meaningful[0]).strip().lower()
        return {
            "action_type": ActionType.ASSERT_TITLE,
            "target_identifier": cmp_mode,
            "value": _strip_quotes(meaningful[1]),
        }

    def assert_value(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 4:
            # TARGET_TYPE + QSTR(field) + CMP + QSTR(expected)
            target_type = _resolve_target_type(meaningful[0])
            field_name = _strip_quotes(meaningful[1])
            cmp_mode = str(meaningful[2]).strip().lower()
            expected = _strip_quotes(meaningful[3])
            return {
                "action_type": ActionType.ASSERT_VALUE,
                "target_type": target_type,
                "target_identifier": field_name,
                "value": f"{cmp_mode}:{expected}",
            }
        # meaningful: QSTR(field) + CMP + QSTR(expected)
        field_name = _strip_quotes(meaningful[0])
        cmp_mode = str(meaningful[1]).strip().lower()
        expected = _strip_quotes(meaningful[2])
        return {
            "action_type": ActionType.ASSERT_VALUE,
            "target_identifier": field_name,
            "value": f"{cmp_mode}:{expected}",
        }

    def assert_variable(self, items):
        meaningful = _filter_items(items)
        # meaningful: QSTR(var_name) + CMP + QSTR(expected)
        var_name = _strip_quotes(meaningful[0])
        cmp_mode = str(meaningful[1]).strip().lower()
        expected = _strip_quotes(meaningful[2])
        return {
            "action_type": ActionType.ASSERT_VARIABLE,
            "target_identifier": var_name,
            "value": f"{cmp_mode}:{expected}",
        }

    # ── State & Control ──────────────────────────────────────────────────

    def wait_seconds(self, items):
        meaningful = _filter_items(items)
        # meaningful contains NUMBER token
        for tok in meaningful:
            if tok.type == "NUMBER":
                return {"action_type": ActionType.WAIT, "value": str(tok)}
        return {"action_type": ActionType.WAIT, "value": "0"}

    def wait_network(self, items):
        return {
            "action_type": ActionType.WAIT,
            "value": "network_idle",
        }

    def store_var(self, items):
        meaningful = _filter_items(items)
        if len(meaningful) == 3:  # TARGET_TYPE + QSTR(source) + QSTR(var)
            return {
                "action_type": ActionType.STORE_VARIABLE,
                "target_type": _resolve_target_type(meaningful[0]),
                "target_identifier": _strip_quotes(meaningful[1]),
                "value": _strip_quotes(meaningful[2]),
            }
        return {
            "action_type": ActionType.STORE_VARIABLE,
            "target_identifier": _strip_quotes(meaningful[0]),
            "value": _strip_quotes(meaningful[1]),
        }

    # ── Top-level rule ───────────────────────────────────────────────────

    def start(self, items):
        """Unwrap the ``start`` rule and return the inner dict."""
        return items[0]


_transformer = _StepTransformer()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_step(
    raw_text: str,
    line_number: int = 0,
) -> tuple[TestStep, ParseError | None]:
    """Parse a single DSL step string into a :class:`TestStep`.

    Returns a ``(TestStep, error_or_none)`` tuple.  If the step does not
    match the built-in grammar, the step is tagged ``ActionType.CUSTOM``
    and a :class:`ParseError` is returned alongside it (as a warning, not
    a hard failure).

    Parameters
    ----------
    raw_text:
        The natural-language step text (without leading bullet / checkbox
        markers).
    line_number:
        1-indexed line number from the source Markdown file.
    """
    text = raw_text.strip()
    variables = _extract_variables(text)

    try:
        tree = _get_parser().parse(text)
        step_dict: dict = _transformer.transform(tree)

        step = TestStep(
            raw_text=raw_text,
            line_number=line_number,
            action_type=step_dict.get("action_type", ActionType.CUSTOM),
            target_type=step_dict.get("target_type", TargetType.GENERIC),
            target_identifier=step_dict.get("target_identifier"),
            value=step_dict.get("value"),
            variables=variables,
        )
        return step, None

    except UnexpectedInput:
        # Grammar did not match → tag as CUSTOM for future resolution
        step = TestStep(
            raw_text=raw_text,
            line_number=line_number,
            action_type=ActionType.CUSTOM,
            variables=variables,
        )
        error = ParseError(
            file_path=None,
            line_number=line_number,
            message=f"Step does not match built-in DSL grammar (tagged CUSTOM): {text}",
            raw_text=raw_text,
        )
        return step, error
