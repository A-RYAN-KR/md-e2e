"""Self-Healing Engine & AI Fallback Processor.

Implements a hybrid self-healing strategy:
- Level 1: Heuristic / Semantic Fuzzy Matching with role confinement,
  opposing verb guards, threshold >= 0.70, and ambiguity lead >= 0.12.
- Level 2: Lightweight LLM fallback when configured.
- Healing Cache: Local persistence in .md_e2e_cache.json with stale cache busting.
- Unified Git diff generator: Outputs valid git apply compatible diffs.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

    from .browser import BrowserConfig

from .models import ActionType, HealingEvent, TargetType, TestStep
from .variables import VariableStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Opposing Verb Guard Definitions
# ---------------------------------------------------------------------------

_OPPOSING_VERB_PAIRS = [
    ({"delete", "remove", "destroy", "erase"}, {"edit", "save", "add", "create", "update", "keep"}),
    ({"cancel", "abort", "discard"}, {"confirm", "submit", "accept", "save", "ok", "apply"}),
    ({"next", "forward", "continue"}, {"back", "previous", "prev"}),
    ({"add", "create", "new"}, {"delete", "remove", "clear"}),
    ({"login", "signin", "sign-in", "in"}, {"logout", "signout", "sign-out", "out"}),
    ({"yes", "enable", "on", "allow"}, {"no", "disable", "off", "deny"}),
    ({"open", "show", "expand"}, {"close", "hide", "collapse"}),
]


def _are_opposing_verbs(orig_text: str, candidate_text: str) -> bool:
    """Return True if original and candidate contain polar opposite action verbs."""
    orig_lower = orig_text.lower()
    cand_lower = candidate_text.lower()
    orig_words = set(orig_lower.split())
    cand_words = set(cand_lower.split())

    orig_compact = orig_lower.replace("-", "").replace(" ", "")
    cand_compact = cand_lower.replace("-", "").replace(" ", "")

    for set_a, set_b in _OPPOSING_VERB_PAIRS:
        # Check token intersection
        if (orig_words & set_a and cand_words & set_b) or (orig_words & set_b and cand_words & set_a):
            return True
        # Check compact phrase presence
        has_a_orig = any(term in orig_compact for term in set_a)
        has_b_orig = any(term in orig_compact for term in set_b)
        has_a_cand = any(term in cand_compact for term in set_a)
        has_b_cand = any(term in cand_compact for term in set_b)
        if (has_a_orig and has_b_cand) or (has_b_orig and has_a_cand):
            return True

    return False


# ---------------------------------------------------------------------------
# Healing Cache
# ---------------------------------------------------------------------------

class HealingCache:
    """Persistent local cache storing healed element selectors."""

    def __init__(self, cache_path: Path | str = ".md_e2e_cache.json"):
        self.cache_path = Path(cache_path)
        self._data: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        """Load cache entries from JSON file if present."""
        if self.cache_path.exists():
            try:
                content = self.cache_path.read_text(encoding="utf-8")
                self._data = json.loads(content)
            except Exception as e:
                logger.warning(f"Failed to load healing cache from {self.cache_path}: {e}")
                self._data = {}

    def save(self) -> None:
        """Persist cache entries to JSON file."""
        try:
            self.cache_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save healing cache to {self.cache_path}: {e}")

    def make_key(
        self,
        suite_name: str,
        case_name: str,
        line_number: int,
        target_identifier: str,
        file_path: Path | str | None = None,
        param_signature: str = "",
    ) -> str:
        """Generate a raw-template cache key immune to dynamic variable collisions."""
        file_prefix = f"{Path(file_path).as_posix()}::" if file_path else ""
        base = f"{file_prefix}{suite_name}::{case_name}::{line_number}::{target_identifier}"
        return f"{base}::{param_signature}" if param_signature else base

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, healed_identifier: str) -> None:
        self._data[key] = healed_identifier
        self.save()

    def invalidate(self, key: str) -> None:
        """Bust a stale cache entry."""
        if key in self._data:
            del self._data[key]
            self.save()


# ---------------------------------------------------------------------------
# Client-side Visible DOM Snapshotting
# ---------------------------------------------------------------------------

_DOM_SNAPSHOT_JS = """
() => {
  const interactiveSelectors = [
    'button', 'a[href]', 'input', 'select', 'textarea',
    '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
    '[tabindex]:not([tabindex="-1"])', '[data-testid]'
  ];
  
  const elements = Array.from(document.querySelectorAll(interactiveSelectors.join(',')));
  
  return elements
    .filter(el => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return (
        rect.width > 0 &&
        rect.height > 0 &&
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0'
      );
    })
    .map(el => ({
      tagName: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.type || el.tagName.toLowerCase(),
      id: el.id || '',
      name: el.getAttribute('name') || '',
      text: (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' '),
      ariaLabel: el.getAttribute('aria-label') || '',
      placeholder: el.getAttribute('placeholder') || '',
      value: el.value || '',
      testId: el.getAttribute('data-testid') || ''
    }));
}
"""


async def clean_dom_snapshot(page: Page) -> list[dict[str, str]]:
    """Extract visible interactive DOM elements from page using client-side JS."""
    try:
        elements = await page.evaluate(_DOM_SNAPSHOT_JS)
        return elements if isinstance(elements, list) else []
    except Exception as e:
        logger.warning(f"Failed to snapshot DOM for healing: {e}")
        return []


# ---------------------------------------------------------------------------
# Level 1: Fuzzy Heuristic Engine
# ---------------------------------------------------------------------------

def _matches_role_confinement(target_type: TargetType, el: dict[str, str]) -> bool:
    """Enforce role & type confinement for candidate elements."""
    tag = el.get("tagName", "")
    role = el.get("role", "")

    match target_type:
        case TargetType.BUTTON:
            return tag == "button" or role in ("button", "submit", "reset") or tag == "input"
        case TargetType.LINK:
            return tag == "a" or role == "link"
        case TargetType.INPUT:
            return tag in ("input", "textarea", "select") or role in ("textbox", "search", "email", "password")
        case TargetType.CHECKBOX:
            return role == "checkbox" or (tag == "input" and el.get("role") == "checkbox")
        case TargetType.RADIO:
            return role == "radio" or (tag == "input" and el.get("role") == "radio")
        case TargetType.HEADING:
            return tag in ("h1", "h2", "h3", "h4", "h5", "h6") or role == "heading"
        case TargetType.TESTID:
            # data-testid elements can be any tag
            return bool(el.get("testId", ""))
        case TargetType.TEXT | TargetType.GENERIC | _:
            return True


# Regex to match trailing metadata like (2), [New], *, etc.
_TRAILING_META_PATTERN = re.compile(
    r'\s*(?:'
    r'\([^)]*\)'      # (2), (New)
    r'|\[[^\]]*\]'    # [New], [2]
    r'|\*+$'          # trailing asterisks
    r')\s*$'
)


def _strip_trailing_metadata(text: str) -> str:
    """Strip trailing metadata patterns from candidate text for better fuzzy matching.

    Removes patterns like " (2)", " [New]", "*" from the end of strings
    so that "Customer Reviews (2)" can match "Customer Reviews".
    """
    result = text
    # Iteratively strip trailing metadata patterns
    for _ in range(3):  # Handle multiple trailing patterns
        stripped = _TRAILING_META_PATTERN.sub('', result).strip()
        if stripped == result:
            break
        result = stripped
    return result or text  # Don't return empty string


def fuzzy_heal(
    target_type: TargetType,
    original_id: str,
    elements: list[dict[str, str]],
    min_threshold: float = 0.70,
    ambiguity_delta: float = 0.12,
) -> str | None:
    """Level 1 Heuristic: Fuzzy match target identifier against visible DOM elements.

    Safeguards:
    1. Minimum similarity threshold >= 0.70
    2. Role & Type confinement matching
    3. Opposing verb guard (Delete <-> Save, etc.)
    4. Ambiguity delta check (top score - second score >= 0.12)
    5. Trailing metadata stripping for better matching (e.g. "(2)", "[New]")
    """
    if not original_id or not elements:
        return None

    scored_candidates: list[tuple[float, str]] = []

    for el in elements:
        if not _matches_role_confinement(target_type, el):
            continue

        # Extract primary text fields
        candidates = [
            el.get("text", ""),
            el.get("ariaLabel", ""),
            el.get("placeholder", ""),
            el.get("value", ""),
            el.get("id", ""),
            el.get("name", ""),
        ]

        best_el_score = 0.0
        best_el_text = ""

        for text in candidates:
            text = text.strip()
            if not text:
                continue

            # Check opposing verb guard
            if _are_opposing_verbs(original_id, text):
                continue

            # Try matching against both raw text and metadata-stripped text
            texts_to_match = [text]
            stripped_text = _strip_trailing_metadata(text)
            if stripped_text != text:
                texts_to_match.append(stripped_text)

            for match_text in texts_to_match:
                ratio = difflib.SequenceMatcher(None, original_id.lower(), match_text.lower()).ratio()
                if ratio > best_el_score:
                    best_el_score = ratio
                    best_el_text = text  # Always use the original text for interaction

        if best_el_score >= min_threshold:
            scored_candidates.append((best_el_score, best_el_text))

    if not scored_candidates:
        return None

    # Sort descending by similarity score
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_score, top_text = scored_candidates[0]

    # Ambiguity check
    if len(scored_candidates) >= 2:
        second_score, _ = scored_candidates[1]
        if (top_score - second_score) < ambiguity_delta:
            # Ambiguous candidates — fail safely
            return None

    return top_text


# ---------------------------------------------------------------------------
# Level 2: Lightweight LLM Fallback (Optional)
# ---------------------------------------------------------------------------

_custom_llm_handler: Callable[[str, list[dict[str, str]]], str] | None = None


def set_llm_handler(
    func: Callable[[str, list[dict[str, str]]], str] | None,
) -> Callable[[str, list[dict[str, str]]], str] | None:
    """Decorator to register a custom LLM handler for Level 2 self-healing."""
    global _custom_llm_handler
    _custom_llm_handler = func
    return func


async def llm_heal(
    step: TestStep,
    elements: list[dict[str, str]],
    api_key: str | None = None,
    custom_handler: Callable[[str, list[dict[str, str]]], str] | None = None,
) -> str | None:
    """Level 2 Fallback: Prompt lightweight LLM or custom handler to find selector."""
    handler = custom_handler or _custom_llm_handler
    if handler:
        try:
            res = handler(step.raw_text, elements)
            return res.strip() if res else None
        except Exception:
            return None

    # If api_key is present (e.g. OpenAI / OpenRouter / compatible), call API
    key = api_key or os.environ.get("MD_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        import json
        import urllib.request

        prompt = (
            f"You are a web test automation self-healing agent.\n"
            f"A test step timed out: {step.raw_text}\n"
            f"Target requested: {step.target_identifier} (Type: {step.target_type.value})\n"
            f"Here are the visible interactive elements on the page:\n"
            f"{json.dumps(elements[:50], indent=2)}\n\n"
            f"Return ONLY the exact text or label of the matching element to interact with, with no other words or markdown formatting."
        )

        base_url = os.environ.get("MD_LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("MD_LLM_MODEL", "gpt-4o-mini")

        try:
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 50,
                }).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            import asyncio
            
            def fetch_llm():
                llm_timeout = int(os.environ.get("MD_LLM_TIMEOUT", "10"))
                with urllib.request.urlopen(req, timeout=llm_timeout) as resp:
                    return resp.read().decode("utf-8")
            
            raw_response = await asyncio.to_thread(fetch_llm)
            data = json.loads(raw_response)
            choice = data["choices"][0]["message"]["content"].strip().strip('"\'`')
            return choice if choice else None
        except Exception as e:
            logger.warning(f"LLM healing API request failed: {e}")
            return None

    return None


# ---------------------------------------------------------------------------
# Self-Healing Coordinator
# ---------------------------------------------------------------------------

_HEALABLE_ACTIONS = {
    ActionType.CLICK,
    ActionType.FILL,
    ActionType.SELECT,
    ActionType.HOVER,
    ActionType.PRESS,
    ActionType.UPLOAD,
    ActionType.CHECK,
    ActionType.UNCHECK,
    ActionType.ASSERT_VISIBLE,
    ActionType.ASSERT_VALUE,
    # NOTE: ASSERT_TITLE intentionally excluded — page titles are not in the
    # interactive DOM snapshot, so healing would match random element text.
}


def is_healable_step(step: TestStep) -> bool:
    """Return True if the step is eligible for self-healing.

    CRITICAL SAFEGUARD: Negative assertions (ASSERT_HIDDEN) must NEVER be healed!
    """
    if step.action_type not in _HEALABLE_ACTIONS:
        return False
    return step.action_type != ActionType.ASSERT_HIDDEN


def _replace_target_identifier(text: str, old_id: str, new_id: str) -> str:
    """Safely replace original target identifier within quoted bounds."""
    if old_id not in text:
        return text
    # Only replace if bounded by matching quotes (single, double, or backticks)
    pattern = re.compile(rf'(["\'`]){re.escape(old_id)}\1')
    # Use a lambda to avoid regex replacement interpretation of new_id
    return pattern.sub(lambda m: f'{m.group(1)}{new_id}{m.group(1)}', text)


async def heal_step(
    page: Page,
    step: TestStep,
    suite_name: str,
    case_name: str,
    file_path: Path | None,
    store: VariableStore,
    config: BrowserConfig,
    cache: HealingCache,
) -> tuple[str | None, HealingEvent | None]:
    """Master Self-Healing Coordinator."""
    if not is_healable_step(step) or not step.target_identifier:
        return None, None

    orig_id = store.resolve(step.target_identifier, line_number=step.line_number)
    # Generate a deterministic signature for parameters in case of matrix run
    param_signature = ""
    if getattr(store, "_data", None):
        # Use hashlib.md5 instead of hash() for deterministic cross-session cache keys
        sig_str = str(sorted(store._data.items()))
        param_signature = hashlib.md5(sig_str.encode("utf-8")).hexdigest()
    cache_key = cache.make_key(suite_name, case_name, step.line_number, step.target_identifier, file_path=file_path, param_signature=str(param_signature))

    # 1. Cache lookup
    cached_val = cache.get(cache_key)
    if cached_val:
        if not _are_opposing_verbs(orig_id, cached_val):
            healed_raw = _replace_target_identifier(step.raw_text, step.target_identifier, cached_val)

            event = HealingEvent(
                file_path=file_path,
                line_number=step.line_number,
                original_text=step.raw_text,
                healed_text=healed_raw,
                original_identifier=orig_id,
                healed_identifier=cached_val,
                strategy_used="cache",
            )
            return cached_val, event

    # 2. Extract DOM snapshot
    elements = await clean_dom_snapshot(page)
    if not elements:
        return None, None

    # 3. Level 1: Fuzzy Heuristic
    healed_id = fuzzy_heal(step.target_type, orig_id, elements)
    strategy = "fuzzy_heuristic"

    # 4. Level 2: LLM Fallback with opposing verb protection
    if not healed_id and config.llm_api_key:
        candidate_llm_id = await llm_heal(step, elements, api_key=config.llm_api_key)
        if candidate_llm_id and not _are_opposing_verbs(orig_id, candidate_llm_id):
            healed_id = candidate_llm_id
            strategy = "llm"

    if healed_id and healed_id != orig_id:
        cache.set(cache_key, healed_id)
        healed_raw = _replace_target_identifier(step.raw_text, step.target_identifier, healed_id)

        event = HealingEvent(
            file_path=file_path,
            line_number=step.line_number,
            original_text=step.raw_text,
            healed_text=healed_raw,
            original_identifier=orig_id,
            healed_identifier=healed_id,
            strategy_used=strategy,
        )
        return healed_id, event

    return None, None


# ---------------------------------------------------------------------------
# Unified Git Apply-Compatible Diff Generator
# ---------------------------------------------------------------------------

def generate_healing_diff(events: list[HealingEvent]) -> str:
    """Generate a strictly valid unified diff format compatible with `git apply`."""
    if not events:
        return ""

    # Group events by file_path
    grouped: dict[str, list[HealingEvent]] = {}
    for ev in events:
        path_str = str(ev.file_path) if ev.file_path else "tests/test_spec.md"
        grouped.setdefault(path_str, []).append(ev)

    diff_lines: list[str] = []

    for file_path, ev_list in grouped.items():
        # Clean relative path for git diff
        rel_path = file_path.replace("\\", "/")
        if not rel_path.startswith("a/") and not rel_path.startswith("b/"):
            a_path = f"a/{rel_path}"
            b_path = f"b/{rel_path}"
        else:
            a_path = rel_path
            b_path = rel_path

        # Required 'diff --git' header for strict git apply compatibility
        diff_lines.append(f"diff --git {a_path} {b_path}")
        diff_lines.append(f"--- {a_path}")
        diff_lines.append(f"+++ {b_path}")

        ev_list.sort(key=lambda e: e.line_number)

        for ev in ev_list:
            line_no = ev.line_number
            diff_lines.append(f"@@ -{line_no},1 +{line_no},1 @@")
            diff_lines.append(f"- {ev.original_text}")
            diff_lines.append(f"+ {ev.healed_text}")

    return "\n".join(diff_lines)
