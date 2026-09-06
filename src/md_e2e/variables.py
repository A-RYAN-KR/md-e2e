"""Runtime variable store and interpolation engine.

Manages the dynamic state context used during test execution.  Supports:
- Jinja-style ``{{var}}`` / ``{{ var }}`` placeholders
- Shell-style ``${VAR}`` placeholders
- Built-in generators (``RANDOM_STRING``, ``RANDOM_EMAIL``, ``TIMESTAMP``)
- Automatic ``ENV_*`` mapping from ``os.environ``

Raises :class:`UndefinedVariableError` when a referenced variable is not
defined rather than silently leaving template literals in output.
"""

from __future__ import annotations

import os
import re
import secrets
import string
import time
from collections.abc import Callable


class UndefinedVariableError(KeyError):
    """Raised when a variable referenced in a step is not in the store."""

    def __init__(self, var_name: str, *, line_number: int | None = None):
        self.var_name = var_name
        self.line_number = line_number
        loc = f" at line {line_number}" if line_number else ""
        super().__init__(
            f"Variable '{var_name}'{loc} is not defined in VariableStore"
        )


# ---------------------------------------------------------------------------
# Built-in generators
# ---------------------------------------------------------------------------

def _random_string(length: int = 12) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _random_email() -> str:
    return f"test_{_random_string(8)}@example.com"


_BUILTIN_GENERATORS: dict[str, Callable[..., str]] = {
    "RANDOM_STRING": _random_string,
    "RANDOM_EMAIL": _random_email,
    "TIMESTAMP": lambda: str(int(time.time())),
}


# ---------------------------------------------------------------------------
# Variable pattern
# ---------------------------------------------------------------------------

# Matches  {{ name }}  or  {{name}}  or  ${ name }  or  ${name}  or  <name>
_VAR_PATTERN = re.compile(
    r"\{\{\s*(?P<jinja>[\w\.\-]+)\s*\}\}"
    r"|"
    r"\$\{\s*(?P<shell>[\w\.\-]+)\s*\}"
    r"|"
    r"<(?P<angle>[\w\.\-]+)>"
)


# ---------------------------------------------------------------------------
# Store Implementation
# ---------------------------------------------------------------------------

class VariableStore:
    """Scoped key-value store with case-insensitive and generated fallbacks.

    Resolution order for ``get(name)``:
    1. Explicitly stored values (exact, then case-insensitive match)
    2. Built-in generators (``RANDOM_STRING``, ``RANDOM_EMAIL``, ``TIMESTAMP``)
    3. Environment variables via ``ENV_*`` prefix
    """

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(initial) if initial else {}
        self._generated: dict[str, str] = {}
        self._local_writes: dict[str, str] = {}

    def store(self, name: str, value: str) -> None:
        """Set a variable in the store."""
        val = str(value)
        target_key = name
        for k in self._data:
            if k.lower() == name.lower():
                target_key = k
                break
        self._data[target_key] = val
        self._local_writes[target_key] = val

    def get(self, name: str) -> str:
        """Resolve a variable name to its string value."""
        # 1. Exact match
        if name in self._data:
            return self._data[name]

        # 2. Built-in generators (cached per store instance for intra-scenario consistency)
        if name in _BUILTIN_GENERATORS:
            if name not in self._generated:
                self._generated[name] = _BUILTIN_GENERATORS[name]()
            return self._generated[name]

        # 3. ENV_* mapping  →  os.environ[KEY_WITHOUT_PREFIX]
        if name.startswith("ENV_"):
            env_key = name[4:]
            if env_key in os.environ:
                return os.environ[env_key]

        # 4. Case-insensitive fallback
        for k, v in self._data.items():
            if k.lower() == name.lower():
                return v

        raise UndefinedVariableError(name)

    def has(self, name: str) -> bool:
        """Check if a variable can be resolved (without generating values)."""
        if name in self._data:
            return True
        # Case-insensitive fallback (consistent with get())
        for k in self._data:
            if k.lower() == name.lower():
                return True
        if name in _BUILTIN_GENERATORS:
            return True
        return bool(name.startswith("ENV_") and name[4:] in os.environ)

    def resolve(self, text: str, *, line_number: int | None = None) -> str:
        """Replace all variable occurrences in text with their current values.

        Parameters
        ----------
        text:
            The raw string potentially containing ``{{ var }}``, ``${var}``, or ``<var>``.
        line_number:
            Optional line number attached to error diagnostics if a variable is missing.

        Returns
        -------
        str
            The interpolated string.

        Raises
        ------
        UndefinedVariableError
            If any referenced variable is not defined.
        """
        def _replacer(m: re.Match) -> str:
            name = m.group("jinja") or m.group("shell") or m.group("angle")
            try:
                return self.get(name)
            except UndefinedVariableError:
                # If an angle-bracket pattern (e.g. <div>, <input>, or unparameterized <tag>)
                # is not defined in the store, preserve it verbatim rather than raising an error.
                if m.group("angle"):
                    return m.group(0)
                raise UndefinedVariableError(name, line_number=line_number)

        return _VAR_PATTERN.sub(_replacer, text)

    def snapshot(self) -> dict[str, str]:
        """Return a shallow copy of all explicitly stored variables."""
        return dict(self._data)

    def merge(self, overrides: dict[str, str]) -> VariableStore:
        """Return a *new* store with current data + overrides (non-mutating).

        The merged store receives a fresh `_generated` cache so that generated
        values (RANDOM_STRING, RANDOM_EMAIL, TIMESTAMP) are newly generated
        for the new execution scope rather than retaining stale values from the parent.
        """
        merged = VariableStore(self._data)
        # Note: self._generated is intentionally NOT copied here (EXEC-006)
        merged._data.update(overrides)
        return merged

    def commit_to(self, target: VariableStore) -> None:
        """Commit locally written variables back into a target parent store."""
        for k, v in self._local_writes.items():
            target.store(k, v)

    def __repr__(self) -> str:
        return f"VariableStore({self._data!r})"
