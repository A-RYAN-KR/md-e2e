"""Custom steps registry and execution engine for md-e2e."""

from __future__ import annotations

import contextvars
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TestStep
from .variables import VariableStore

@dataclass
class CustomStepEntry:
    pattern: re.Pattern
    handler: Callable[..., Any]
    source_dir: Path

# Registry of custom steps
_custom_steps_registry: list[CustomStepEntry] = []

# ContextVar to make the pytest Request object accessible during custom step execution
current_request: contextvars.ContextVar[Any] = contextvars.ContextVar("current_request", default=None)


class StepNotImplementedError(NotImplementedError):
    """Raised for ActionType.CUSTOM steps with no registered handler."""

    def __init__(self, step: TestStep):
        self.step = step
        file_loc = f"{step.file_path}:" if getattr(step, "file_path", None) else ""
        super().__init__(
            f"\n[md-e2e] Unrecognized step at {file_loc}{step.line_number}:\n"
            f"  '{step.raw_text}'\n\n"
            f"To implement this step, define a handler in conftest.py:\n"
            f"  @custom_step(r'{re.escape(step.raw_text)}')\n"
            f"  async def my_step(page):\n"
            f"      # Your Playwright logic\n"
        )


def custom_step(pattern: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a project-specific custom step handler.

    Parameters
    ----------
    pattern : str
        A regular expression pattern to match against the step raw text.
        Can contain named capture groups (e.g. `(?P<email>[^"]+)`) or
        positional capture groups (e.g. `([^"]+)`) which will be injected
        as arguments.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        compiled = re.compile(pattern)
        try:
            frame = inspect.stack()[1]
            source_dir = Path(frame.filename).parent.resolve()
        except Exception:
            source_dir = Path.cwd().resolve()
        _custom_steps_registry.append(CustomStepEntry(compiled, func, source_dir))
        return func
    return decorator


def clear_custom_steps() -> None:
    """Clear all registered custom steps from the global registry."""
    _custom_steps_registry.clear()



async def _execute_custom_step(
    step: TestStep,
    page: Any,
    store: VariableStore,
) -> None:
    """Find a matching registered custom step handler, bind arguments, and execute it.

    Supports both sync and async handlers, and injects 'page', 'store',
    'context', regex matched groups, and pytest fixtures if requested.
    """
    # 1. Resolve variables in step.raw_text
    resolved_text = store.resolve(step.raw_text, line_number=step.line_number)

    # 2. Find a matching custom step handler
    handler: Callable[..., Any] | None = None
    match: re.Match | None = None

    for entry in _custom_steps_registry:
        if getattr(step, "file_path", None):
            try:
                step_dir = step.file_path.parent.resolve()
                if entry.source_dir not in step_dir.parents and entry.source_dir != step_dir:
                    continue
            except Exception:
                pass

        m = entry.pattern.match(resolved_text)
        if m:
            handler = entry.handler
            match = m
            break

    if handler is None:
        raise StepNotImplementedError(step)

    assert match is not None
    # 3. Dynamic argument injection based on inspect.signature
    kwargs = match.groupdict()
    # Separate unnamed positional groups from named groups
    if match.re.groupindex:
        named_indices = set(match.re.groupindex.values())
        unnamed_positional_args = [
            val for idx, val in enumerate(match.groups(), start=1) if idx not in named_indices
        ]
    else:
        unnamed_positional_args = list(match.groups())

    sig = inspect.signature(handler)
    req = current_request.get()

    bind_kwargs: dict[str, Any] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "page":
            bind_kwargs[param_name] = page
        elif param_name in ("context_store", "store"):
            bind_kwargs[param_name] = store
        elif param_name == "context":
            bind_kwargs["context"] = getattr(page, "context", None)
        elif param_name in kwargs:
            bind_kwargs[param_name] = kwargs[param_name]
        else:
            # Check if this parameter can be resolved as a pytest fixture
            resolved_fixture = False
            if req is not None and hasattr(req, "getfixturevalue"):
                try:
                    bind_kwargs[param_name] = req.getfixturevalue(param_name)
                    resolved_fixture = True
                except Exception:
                    pass

            if not resolved_fixture and param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                if unnamed_positional_args:
                    bind_kwargs[param_name] = unnamed_positional_args.pop(0)

    # Bind args to signature with clear diagnostics on failure
    try:
        bound = sig.bind(**bind_kwargs)
        bound.apply_defaults()
    except TypeError as exc:
        raise TypeError(
            f"Failed to bind arguments for custom step {step.raw_text!r} to handler {handler.__name__!r}: {exc}"
        ) from exc

    # 4. Invoke
    if inspect.iscoroutinefunction(handler):
        await handler(*bound.args, **bound.kwargs)
    else:
        handler(*bound.args, **bound.kwargs)
