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
    r"\{\{\s*(?P<jinja>\w+)\s*\}\}"
    r"|"
    r"\$\{\s*(?P<shell>\w+)\s*\}"
    r"|"
    r"<(?P<angle>\w+)>",
)


# ---------------------------------------------------------------------------
# VariableStore
# ---------------------------------------------------------------------------

class VariableStore:
    """Dict-like runtime variable context for test execution.

    Variables are resolved in this priority order:
    1. Explicitly stored values (via :meth:`store` or data-matrix rows)
    2. Built-in generators (``RANDOM_STRING``, ``RANDOM_EMAIL``, ``TIMESTAMP``)
    3. Environment variables with ``ENV_`` prefix auto-mapping
       (e.g., ``ENV_BASE_URL`` → ``os.environ["BASE_URL"]``)
    """

    def __init__(self, initial: dict[str, str] | None = None):
        self._data: dict[str, str] = {}
        if initial:
            self._data.update(initial)

    def store(self, name: str, value: str) -> None:
        """Set a variable value."""
        self._data[name] = value

    def get(self, name: str) -> str:
        """Retrieve a variable value.

        Resolution order: explicit store → built-in generators → ENV_* mapping.

        Raises
        ------
        UndefinedVariableError
            If the variable cannot be resolved through any source.
        """
        # 1. Explicitly stored (exact or case-insensitive)
        if name in self._data:
            return self._data[name]
        for k, v in self._data.items():
            if k.lower() == name.lower():
                return v

        # 2. Built-in generators
        if name in _BUILTIN_GENERATORS:
            val = _BUILTIN_GENERATORS[name]()
            # Cache generated value for consistency within a scenario
            self._data[name] = val
            return val

        # 3. ENV_* mapping  →  os.environ[KEY_WITHOUT_PREFIX]
        if name.startswith("ENV_"):
            env_key = name[4:]  # strip "ENV_"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                return env_val

        raise UndefinedVariableError(name)

    def has(self, name: str) -> bool:
        """Check if a variable can be resolved (without generating values)."""
        if name in self._data:
            return True
        if name in _BUILTIN_GENERATORS:
            return True
        return bool(name.startswith("ENV_") and name[4:] in os.environ)

    def resolve(
        self,
        text: str,
        *,
        line_number: int | None = None,
    ) -> str:
        """Replace all ``{{var}}`` and ``${var}`` placeholders in *text*.

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
                raise UndefinedVariableError(name, line_number=line_number)

        return _VAR_PATTERN.sub(_replacer, text)

    def snapshot(self) -> dict[str, str]:
        """Return a shallow copy of all explicitly stored variables."""
        return dict(self._data)

    def merge(self, overrides: dict[str, str]) -> VariableStore:
        """Return a *new* store with current data + overrides (non-mutating)."""
        merged = VariableStore(self._data)
        merged._data.update(overrides)
        return merged

    def __repr__(self) -> str:
        return f"VariableStore({self._data!r})"
