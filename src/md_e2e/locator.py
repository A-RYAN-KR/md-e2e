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

_RAW_SELECTOR_PATTERN = re.compile(
    r"^(?:"
    r"\.[a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9_\-]+)*|"  # .class.names
    r"#[a-zA-Z0-9_\-]+|"                       # #ids
    r"\[.+?\]|"                                # [attributes]
    r"//.+|"                                   # //xpath
    r"(?:css|xpath|id|name|data-testid)=.+"                # engine=value
    r")$"
)


def is_raw_selector(identifier: str) -> bool:
    """Return ``True`` if *identifier* looks like a CSS/XPath selector."""
    ident = identifier.strip()
    return bool(_RAW_SELECTOR_PATTERN.match(ident)) or ">>" in ident


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
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]").replace("'", "\\'")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_locator(
    page: Page,
    target_type: TargetType,
    identifier: str,
) -> Locator:
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
        return page.locator(identifier)

    # Compile regex pattern to match exact whole-string case-insensitively,
    # preventing strict mode violations (e.g. "Male" matching "Female").
    pattern = re.compile(r"^\s*" + re.escape(identifier) + r"\s*$", re.IGNORECASE)
    # Properly escape for CSS attribute selectors — handles ", \, ], '
    css_escaped = _css_escape_value(identifier)

    # 2. Explicit target type
    match target_type:
        case TargetType.TESTID:
            return page.get_by_test_id(identifier)

        case TargetType.BUTTON:
            return page.get_by_role("button", name=pattern).or_(
                page.locator(
                    f'input[type="submit"][value="{css_escaped}" i],'
                    f'input[type="button"][value="{css_escaped}" i]'
                )
            ).first

        case TargetType.LINK:
            if identifier.startswith("http://") or identifier.startswith("https://") or identifier.startswith("/"):
                return (
                    page.locator(f'a[href*="{css_escaped}" i]')
                    .or_(page.locator(f'a[href="{css_escaped}"]'))
                    .or_(page.locator("a:visible").filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE)))
                ).first
            return (
                page.locator("a:visible").filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE))
                .or_(page.get_by_role("link", name=pattern))
                .or_(page.get_by_role("link", name=re.compile(re.escape(identifier), re.IGNORECASE)))
                .or_(page.locator(f'a[href*="{css_escaped}" i]'))
            ).first

        case TargetType.HEADING:
            # High-priority exact match, then filter, then substring
            exact_pattern = re.compile(r"^\s*" + re.escape(identifier) + r"\s*$", re.IGNORECASE)
            return page.locator("h1, h2, h3, h4, h5, h6").filter(has_text=exact_pattern).or_(
                page.locator("h1, h2, h3, h4, h5, h6").filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE))
            ).first

        case TargetType.CHECKBOX:
            return page.get_by_role("checkbox", name=pattern).or_(
                page.get_by_label(pattern)
            ).first

        case TargetType.RADIO:
            return page.get_by_role("radio", name=pattern).or_(
                page.get_by_label(pattern)
            ).first

        case TargetType.INPUT:
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)

            # -- Layer 1: Standard semantic accessibility --
            semantic = (
                page.get_by_role("textbox", name=pattern)
                .or_(page.get_by_role("searchbox", name=pattern))
                .or_(page.get_by_placeholder(pattern))
                .or_(page.locator(
                    f'input[type="search"], input[name="{css_escaped}" i], input[id="{css_escaped}" i], '
                    f'textarea[name="{css_escaped}" i], input[placeholder*="{css_escaped}" i], input[aria-label*="{css_escaped}" i]'
                ))
                .or_(page.get_by_placeholder(contains_pattern))
                .or_(page.get_by_role("textbox", name=contains_pattern))
                .or_(page.get_by_label(pattern))
            )

            # -- Layer 2: DOM proximity heuristics --
            # Handles non-semantic HTML where <label> lacks htmlFor/for
            # e.g. <label>First Name</label><input type="text" />
            proximity = (
                # Adjacent sibling: <label>X</label> + <input/>
                page.locator(
                    f'label:has-text("{css_escaped}") + input,'
                    f' label:has-text("{css_escaped}") + textarea,'
                    f' label:has-text("{css_escaped}") + select,'
                    f' label:has-text("{css_escaped}") ~ input'
                )
                .or_(
                    # Container/form-group: <div><label>X</label><input/></div>
                    page.locator(
                        ':is(.form-group, .form-control, .field, div, p)'
                        f':has(> label:has-text("{css_escaped}"))'
                    ).locator("input, textarea, select")
                )
            )

            # -- Layer 3: Fuzzy attribute inference --
            # Matches data-testid="shipping-first-name", name="firstName", etc.
            attr_variants = _generate_attribute_variants(identifier)
            attr_selectors: list[str] = []
            for v in attr_variants:
                v_escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                attr_selectors.extend([
                    f'input[name*="{v_escaped}" i]',
                    f'input[id*="{v_escaped}" i]',
                    f'input[data-testid*="{v_escaped}" i]',
                    f'input[placeholder*="{v_escaped}" i]',
                    f'textarea[name*="{v_escaped}" i]',
                    f'textarea[id*="{v_escaped}" i]',
                    f'textarea[data-testid*="{v_escaped}" i]',
                ])
            fuzzy_attrs = page.locator(", ".join(attr_selectors))

            return semantic.or_(proximity).or_(fuzzy_attrs).first

        case TargetType.TEXT:
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return (
                page.get_by_text(pattern)
                .or_(page.get_by_text(contains_pattern))
                .or_(page.get_by_role("heading", name=pattern))
                .or_(page.get_by_role("heading", name=contains_pattern))
            ).first

        case TargetType.GENERIC | _:
            # Comprehensive semantic fallback
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return (
                page.get_by_role("button", name=pattern)
                .or_(page.get_by_role("link", name=pattern))
                .or_(page.get_by_label(pattern))
                .or_(page.get_by_placeholder(pattern))
                .or_(page.get_by_text(pattern))
                .or_(page.get_by_text(contains_pattern))
            ).first
