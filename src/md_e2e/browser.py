"""Playwright browser lifecycle manager.

Provides :class:`BrowserConfig` for declarative configuration and
:class:`BrowserSession` as an async context manager that handles browser
launch, context creation (with video / trace / auth support), and teardown.

Architecture
------------
* **Browser** is launched **once per suite** (expensive OS process).
* **BrowserContext + Page** are created **per scenario** (instantaneous,
  fully isolated cookies / storage / cache).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from playwright.async_api import (
    Browser,
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)


@dataclass
class BrowserConfig:
    """Declarative configuration for browser sessions.

    Attributes
    ----------
    browser_type : ``"chromium"`` | ``"firefox"`` | ``"webkit"``
        Which Playwright browser engine to use.
    headless : bool
        Run in headless mode (default ``True``).
    viewport : dict | None
        Viewport size, e.g. ``{"width": 1280, "height": 720}``.
    locale : str | None
        Browser locale, e.g. ``"en-US"``.
    video_dir : Path | str | None
        Directory for video recordings.  ``None`` disables recording.
    trace_dir : Path | str | None
        Directory for Playwright trace archives.  Traces are captured
        when a scenario fails.
    storage_state : Path | str | None
        Path to a JSON file with saved authentication state.
    extra_http_headers : dict[str, str] | None
        Additional HTTP headers injected into every request.
    slow_mo : int
        Milliseconds to slow down each Playwright operation (default 0).
    timeout : int
        Default timeout in milliseconds for actions and assertions
        (default 30_000).
    screenshot_dir : Path | str | None
        Directory for failure screenshots.  ``None`` disables.
    """

    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    viewport: dict[str, int] | None = None
    locale: str | None = None
    video_dir: Path | str | None = None
    trace_dir: Path | str | None = None
    storage_state: Path | str | None = None
    extra_http_headers: dict[str, str] | None = None
    slow_mo: int = 0
    timeout: int = 30_000
    screenshot_dir: Path | str | None = None
    enable_healing: bool = True
    healing_cache_path: Path | str | None = ".md_e2e_cache.json"
    llm_api_key: str | None = None
    clean_session: bool = False

    def __post_init__(self) -> None:
        if self.llm_api_key is None:
            self.llm_api_key = os.environ.get("MD_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")



class BrowserSession:
    """Async context manager for Playwright browser lifecycle.

    Usage::

        async with BrowserSession(config) as session:
            # session.browser  — the Browser instance (reusable)
            # Use session.new_context() per scenario
            async with session.new_context() as (context, page):
                await page.goto("https://example.com")
    """

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("BrowserSession not entered; use 'async with'")
        return self._browser

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()

        # Select browser engine
        engine: BrowserType = getattr(
            self._playwright, self.config.browser_type
        )

        self._browser = await engine.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def new_context(
        self,
        *,
        trace: bool = False,
    ) -> _ContextManager:
        """Create a new isolated BrowserContext + Page.

        Parameters
        ----------
        trace : bool
            If ``True``, start Playwright tracing on this context.
            Tracing is saved to ``config.trace_dir`` when the context
            exits with an error.
        """
        return _ContextManager(self, trace=trace)


class _ContextManager:
    """Async context manager that creates and tears down a BrowserContext."""

    def __init__(self, session: BrowserSession, *, trace: bool = False):
        self._session = session
        self._trace = trace
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._trace_name: str | None = None

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Context not entered")
        return self._context

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Context not entered")
        return self._page

    async def __aenter__(self) -> tuple[BrowserContext, Page]:
        cfg = self._session.config

        # Build context options
        ctx_opts: dict[str, Any] = {}
        if cfg.viewport:
            ctx_opts["viewport"] = cfg.viewport
        if cfg.locale:
            ctx_opts["locale"] = cfg.locale
        if cfg.storage_state:
            ctx_opts["storage_state"] = str(cfg.storage_state)
        if cfg.extra_http_headers:
            ctx_opts["extra_http_headers"] = cfg.extra_http_headers
        if cfg.video_dir:
            ctx_opts["record_video_dir"] = str(cfg.video_dir)

        self._context = await self._session.browser.new_context(**ctx_opts)
        self._context.set_default_timeout(cfg.timeout)

        # Start tracing if requested
        if self._trace and cfg.trace_dir:
            await self._context.tracing.start(
                screenshots=True, snapshots=True, sources=True,
            )

        self._page = await self._context.new_page()
        return self._context, self._page

    async def save_trace(self, name: str) -> Path | None:
        """Save trace archive manually. Returns path or None."""
        cfg = self._session.config
        if self._context and self._trace and cfg.trace_dir:
            trace_path = Path(cfg.trace_dir) / f"{name}.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.tracing.stop(path=str(trace_path))
            self._trace = False
            return trace_path
        return None

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        cfg = self._session.config

        # Save trace on failure
        if exc_type and self._trace and cfg.trace_dir and self._context:
            try:
                trace_path = Path(cfg.trace_dir) / "failure_trace.zip"
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                await self._context.tracing.stop(path=str(trace_path))
                self._trace = False
            except Exception:
                pass  # Don't mask the original exception
        elif self._trace and self._context:
            # Discard trace if no failure
            try:
                await self._context.tracing.stop()
                self._trace = False
            except Exception:
                pass

        if self._context:
            await self._context.close()
