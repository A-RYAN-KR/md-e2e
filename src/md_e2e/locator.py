"""Semantic accessibility-first locator resolver.

Translates ``(TargetType, identifier)`` pairs into Playwright ``Locator``
objects using a priority chain of accessibility-based selectors joined
with ``.or_()``.

Using ``.or_()`` is critical: Playwright locators are **lazy** — calling
``page.get_by_label(...)`` never queries the DOM until an action is
performed.  A ``try … except`` fallback chain would wait for the full
timeout on each miss.  ``.or_()`` tells Playwright's auto-wait engine to
match whichever strategy resolves first, in a single timeout window.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

from .models import TargetType

# ---------------------------------------------------------------------------
# Raw selector detection
# ---------------------------------------------------------------------------

_ATTR_SELECTOR_PART = (
    r"\[\s*(?:"
    r"(?:data|aria)-[a-zA-Z0-9_\-]+|"
    r"disabled|required|checked|selected|readonly|multiple|hidden|autofocus|open|novalidate|reversed|formnovalidate|"
    r"[a-zA-Z_][a-zA-Z0-9_\-:]*\s*[*^$|~]?=\s*(?:\"[^\"]*\"|'[^']*'|[^\]\s]+)"
    r")\s*\]"
)

_RAW_SELECTOR_PATTERN = re.compile(
    r"^(?:"
    r"\.[a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9_\-]+)*|"  # .class.names
    r"#[a-zA-Z0-9_\-]+|"                       # #ids
    rf"(?:{_ATTR_SELECTOR_PART})+|"             # [attr=value] or [disabled] attribute selectors
    r"//.+|"                                   # //xpath
    r"(?:css|xpath|id|name|data-testid)=.+"    # engine=value
    r")$"
)


_HTML_TAGS = frozenset({
    "a", "abbr", "address", "area", "article", "aside", "audio", "b", "base",
    "bdi", "bdo", "blockquote", "body", "br", "button", "canvas", "caption",
    "cite", "code", "col", "colgroup", "data", "datalist", "dd", "del",
    "details", "dfn", "dialog", "div", "dl", "dt", "em", "embed", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "head", "header", "hgroup", "hr", "html", "i", "iframe", "img",
    "input", "ins", "kbd", "label", "legend", "li", "link", "main", "map",
    "mark", "menu", "meta", "meter", "nav", "noscript", "object", "ol",
    "optgroup", "option", "output", "p", "picture", "pre", "progress", "q",
    "rp", "rt", "ruby", "s", "samp", "script", "section", "select", "slot",
    "small", "source", "span", "strong", "style", "sub", "summary", "sup",
    "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead",
    "time", "title", "tr", "track", "u", "ul", "var", "video", "wbr", "svg", "path"
})

_SELECTOR_PREFIXES = ("text=", "has-text=", "css=", "xpath=", "id=", "name=", "data-testid=")

_TAG_COMPOUND_PATTERN = re.compile(
    rf"^([a-zA-Z][a-zA-Z0-9_\-]*)"
    rf"(?:"
    rf"\.[a-zA-Z0-9_\-]+|"
    rf"#[a-zA-Z0-9_\-]+|"
    rf":visible|"
    rf":is\([^)]+\)|"
    rf":has-text\([^)]+\)|"
    rf":text\([^)]+\)|"
    rf"{_ATTR_SELECTOR_PART}"
    rf")*$"
)


def _is_selector_token(token: str) -> bool:
    """Return True if token is a valid CSS/Playwright selector segment."""
    t = token.strip()
    if not t:
        return False
    if _RAW_SELECTOR_PATTERN.match(t):
        return True
    if any(t.startswith(pfx) for pfx in _SELECTOR_PREFIXES):
        return True
    m = _TAG_COMPOUND_PATTERN.match(t)
    if m:
        tag_name = m.group(1)
        if len(tag_name) == 1 and tag_name.isupper():
            return False
        if tag_name.lower() in _HTML_TAGS:
            return True
    return False


def is_raw_selector(identifier: str) -> bool:
    """Return ``True`` if *identifier* looks like a CSS/XPath selector."""
    ident = identifier.strip()
    if not ident:
        return False
    if _RAW_SELECTOR_PATTERN.match(ident):
        return True
    # Selector combinator '>>': all chained parts must be valid selector tokens,
    # not natural-language labels like 'Next >>', '>> Back', 'A >> B', or 'Next >> Page'
    if ">>" in ident:
        if ident.startswith(">>") or ident.endswith(">>"):
            return False
        parts = [p.strip() for p in ident.split(">>")]
        if all(parts) and len(parts) >= 2:
            return all(_is_selector_token(part) for part in parts)
    return False


# ---------------------------------------------------------------------------
# Attribute variant generation for fuzzy matching
# ---------------------------------------------------------------------------

def _generate_attribute_variants(text: str) -> list[str]:
    """Convert a human-readable label into common attribute naming conventions.

    For example, ``"First Name"`` yields::

        ["First Name", "first-name", "first_name", "firstName", "firstname"]

    These variants are used for fuzzy matching against ``name``, ``id``,
    ``data-testid``, and ``placeholder`` attributes when semantic selectors
    fail (e.g. ``<label>`` without ``htmlFor``).
    """
    clean = re.sub(r"[^\w\s]", "", text).strip()
    words = clean.split()
    if not words:
        return [text]

    kebab = "-".join(w.lower() for w in words)
    snake = "_".join(w.lower() for w in words)
    camel = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    flat = "".join(w.lower() for w in words)

    return list(dict.fromkeys([clean, kebab, snake, camel, flat]))


# ---------------------------------------------------------------------------
# CSS value escaping
# ---------------------------------------------------------------------------

def _css_escape_value(s: str) -> str:
    """Escape a string for safe interpolation inside CSS attribute selectors like [attr="value"]."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace("]", "\\]")
        .replace("\r", "\\d ")
        .replace("\n", "\\a ")
        .replace("\f", "\\c ")
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TierList(list):
    """List of Locator tiers annotated with primary_count metadata for tier-aware resolution."""

    def __init__(self, items, primary_count: int | None = None) -> None:
        super().__init__(items)
        self.primary_count = primary_count if primary_count is not None else len(items)


def resolve_locator(
    page: Page,
    target_type: TargetType,
    identifier: str,
) -> list[Locator]:
    """Resolve a ``(TargetType, identifier)`` pair into a Playwright Locator.

    Resolution strategy:

    1. **Raw selectors** — if *identifier* looks like CSS/XPath (starts with
       ``#``, ``.``, ``//``, ``css=``, ``xpath=``, etc.), pass it directly
       to ``page.locator()``.

    2. **Explicit role** — when *target_type* is ``BUTTON``, ``LINK``,
       ``HEADING``, etc., use ``page.get_by_role()`` as the primary
       strategy with ``.or_()`` fallbacks.

    3. **INPUT** — semantic selectors, then DOM proximity heuristics
       (adjacent sibling / parent container), then fuzzy attribute matching
       against ``name``, ``id``, ``data-testid``, ``placeholder`` using
       kebab-case / camelCase / snake_case variants.

    4. **GENERIC** — comprehensive fallback:
       ``get_by_label .or_ get_by_placeholder .or_ get_by_role("button")
       .or_ get_by_role("link") .or_ get_by_text``.

    All ``.or_()`` chains are resolved **simultaneously** within a single
    Playwright auto-wait timeout — no serial timeout penalties.
    """
    identifier = identifier.strip()

    # 1. Direct CSS / XPath / attribute selector
    if is_raw_selector(identifier):
        return [page.locator(identifier)]

    # Compile regex pattern to match exact whole-string case-insensitively,
    # preventing strict mode violations (e.g. "Male" matching "Female").
    pattern = re.compile(r"^\s*" + re.escape(identifier) + r"\s*$", re.IGNORECASE)
    # Properly escape for CSS attribute selectors — handles ", \, ], '
    css_escaped = _css_escape_value(identifier)

    # 2. Explicit target type
    match target_type:
        case TargetType.TESTID:
            return [page.get_by_test_id(identifier)]

        case TargetType.BUTTON:
            return [
                page.get_by_role("button", name=pattern),
                page.locator(
                    f'input[type="submit"][value="{css_escaped}" i],'
                    f'input[type="button"][value="{css_escaped}" i]'
                )
            ]

        case TargetType.LINK:
            if identifier.startswith("http://") or identifier.startswith("https://") or identifier.startswith("/"):
                return [
                    page.locator(f'a[href="{css_escaped}"]'),
                    page.locator(f'a[href*="{css_escaped}" i]'),
                    page.locator("a:visible").filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE))
                ]
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return TierList([
                page.get_by_role("link", name=pattern),
                page.locator("a:visible").filter(has_text=pattern),
                page.get_by_role("link", name=contains_pattern),
                page.locator("a:visible").filter(has_text=contains_pattern),
                page.locator(f'a[href*="{css_escaped}" i]')
            ], primary_count=4)

        case TargetType.HEADING:
            # High-priority exact match, then filter, then substring
            exact_pattern = re.compile(r"^\s*" + re.escape(identifier) + r"\s*$", re.IGNORECASE)
            return [
                page.locator("h1, h2, h3, h4, h5, h6").filter(has_text=exact_pattern),
                page.locator("h1, h2, h3, h4, h5, h6").filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE))
            ]

        case TargetType.CHECKBOX:
            return [
                page.get_by_role("checkbox", name=pattern),
                page.get_by_label(pattern)
            ]

        case TargetType.RADIO:
            return [
                page.get_by_role("radio", name=pattern),
                page.get_by_label(pattern)
            ]

        case TargetType.INPUT:
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)

            # -- Layer 1: Standard semantic accessibility --
            semantic = [
                page.get_by_role("textbox", name=pattern),
                page.get_by_role("searchbox", name=pattern),
                page.get_by_placeholder(pattern),
                page.locator(
                    f'input[name="{css_escaped}" i], input[id="{css_escaped}" i], '
                    f'textarea[name="{css_escaped}" i], input[placeholder*="{css_escaped}" i], input[aria-label*="{css_escaped}" i]'
                ),
                page.get_by_placeholder(contains_pattern),
                page.get_by_role("textbox", name=contains_pattern),
                page.get_by_label(pattern)
            ]

            # -- Layer 2: DOM proximity heuristics --
            # Handles non-semantic HTML where <label> lacks htmlFor/for
            # e.g. <label>First Name</label><input type="text" />
            proximity = [
                # Adjacent sibling: <label>X</label> + <input/>
                page.locator(
                    f'label:has-text("{css_escaped}") + input,'
                    f' label:has-text("{css_escaped}") + textarea,'
                    f' label:has-text("{css_escaped}") + select,'
                    f' label:has-text("{css_escaped}") ~ input'
                ),
                # Container/form-group: <div><label>X</label><input/></div>
                page.locator(
                    ':is(.form-group, .form-control, .field, div, p)'
                    f':has(> label:has-text("{css_escaped}"))'
                ).locator("input, textarea, select")
            ]

            # -- Layer 3: Fuzzy attribute inference --
            # Matches data-testid="shipping-first-name", name="firstName", etc.
            attr_variants = _generate_attribute_variants(identifier)
            attr_selectors: list[str] = []
            for v in attr_variants:
                v_escaped = _css_escape_value(v)
                attr_selectors.extend([
                    f'input[name*="{v_escaped}" i]',
                    f'input[id*="{v_escaped}" i]',
                    f'input[data-testid*="{v_escaped}" i]',
                    f'input[placeholder*="{v_escaped}" i]',
                    f'textarea[name*="{v_escaped}" i]',
                    f'textarea[id*="{v_escaped}" i]',
                    f'textarea[data-testid*="{v_escaped}" i]',
                ])
            fuzzy_attrs = [page.locator(", ".join(attr_selectors))]

            return TierList(semantic + proximity + fuzzy_attrs, primary_count=len(semantic))

        case TargetType.TEXT:
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return [
                page.get_by_text(pattern),
                page.get_by_text(contains_pattern),
                page.get_by_role("heading", name=pattern),
                page.get_by_role("heading", name=contains_pattern)
            ]

        case TargetType.GENERIC | _:
            # Comprehensive semantic fallback
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            semantic_roles = [
                page.get_by_role("button", name=pattern),
                page.get_by_role("link", name=pattern),
                page.get_by_label(pattern),
                page.get_by_placeholder(pattern),
            ]
            text_fallbacks = [
                page.get_by_text(pattern),
                page.get_by_text(contains_pattern)
            ]
            return TierList(semantic_roles + text_fallbacks, primary_count=len(semantic_roles))
