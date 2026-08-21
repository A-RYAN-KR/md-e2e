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
    r"#[\w-]"           # CSS ID selector:  #submit-btn
    r"|\.[\w-]"         # CSS class selector: .btn-primary
    r"|//"              # XPath: //div[@id='x']
    r"|css="            # Explicit css= prefix
    r"|xpath="          # Explicit xpath= prefix
    r"|data-testid="    # Explicit test-id prefix
    r"|>>"              # Playwright chained selector
    r"|\["              # Attribute selector: [data-testid="x"]
    r")"
)


def is_raw_selector(identifier: str) -> bool:
    """Return ``True`` if *identifier* looks like a CSS/XPath selector."""
    ident = identifier.strip()
    return bool(_RAW_SELECTOR_PATTERN.match(ident)) or ">>" in ident


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

    3. **INPUT** — ``get_by_label .or_ get_by_placeholder .or_ get_by_role("textbox")``.

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
    css_escaped = identifier.replace("\\", "\\\\").replace('"', '\\"')

    # 2. Explicit target type
    match target_type:
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
            return (
                page.locator("h1:visible, h2:visible, h3:visible, h4:visible, h5:visible, h6:visible, [role=heading]:visible")
                .filter(has_text=re.compile(re.escape(identifier), re.IGNORECASE))
                .or_(page.get_by_role("heading", name=pattern))
                .or_(page.get_by_role("heading", name=re.compile(re.escape(identifier), re.IGNORECASE)))
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
            return (
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
            ).first

        case TargetType.TEXT:
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return (
                page.locator("*:visible").filter(has_text=contains_pattern)
                .or_(page.get_by_text(contains_pattern))
            ).first

        case TargetType.GENERIC | _:
            # Comprehensive semantic fallback
            contains_pattern = re.compile(re.escape(identifier), re.IGNORECASE)
            return (
                page.locator("*:visible").filter(has_text=contains_pattern)
                .or_(page.get_by_label(pattern))
                .or_(page.get_by_placeholder(pattern))
                .or_(page.get_by_role("button", name=pattern))
                .or_(page.get_by_role("link", name=pattern))
                .or_(page.get_by_text(contains_pattern))
            ).first
