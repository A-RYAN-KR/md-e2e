"""Codegen Action Recorder — records user actions in headed browser as E2E Markdown test specs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright
from rich import print as rprint


def format_action_to_dsl(action_data: dict[str, Any]) -> str:
    """Format recorded action data into E2E Markdown DSL step."""
    action = action_data.get("action")
    target = str(action_data.get("target", ""))
    value = str(action_data.get("value", ""))
    url = str(action_data.get("url", ""))

    # Clean quotes
    target = target.replace('"', '\\"')
    value = value.replace('"', '\\"')
    url = url.replace('"', '\\"')

    if action == "NAVIGATE":
        return f'- Navigate to "{url}"'
    elif action == "CLICK_LINK":
        return f'- Click link "{target}"'
    elif action == "CLICK_BUTTON":
        return f'- Click button "{target}"'
    elif action == "FILL":
        return f'- Fill input "{target}" with "{value}"'
    elif action == "SELECT":
        return f'- Select "{value}" from "{target}"'
    elif action == "CHECK":
        return f'- Check checkbox "{target}"'
    elif action == "UNCHECK":
        return f'- Uncheck checkbox "{target}"'
    
    return ""


def generate_markdown_spec(url: str, steps: list[str]) -> str:
    """Generate Markdown E2E test specification file content."""
    dsl_steps = "\n".join(steps)
    return f"""# Recorded Test Suite

This E2E test suite was recorded automatically starting from {url}.

## Recorded Scenario
{dsl_steps}
"""


async def record_session(url: str, output_path: Path) -> None:
    """Start a headed Playwright browser session, inject recorder script, and save steps on exit."""
    rprint(f"[bold blue]Starting recorder at URL:[/bold blue] {url}")
    rprint("[bold yellow]Interact with the page to record actions. Close the browser window to stop and save.[/bold yellow]")

    steps: list[str] = []
    # Deduplicate successive duplicate navigations / clicks
    last_step: str = ""

    async def on_action(source: Any, action_data: dict[str, Any]) -> None:
        dsl_line = format_action_to_dsl(action_data)
        nonlocal last_step
        if dsl_line and dsl_line != last_step:
            steps.append(dsl_line)
            last_step = dsl_line
            rprint(f"[green]Recorded action:[/green] {dsl_line}")

    # Injection script
    js_recorder = """
    (function() {
        // Expose initial navigation
        if (window.location.href !== "about:blank") {
            window.md_e2e_record_action({ action: "NAVIGATE", url: window.location.href });
        }

        // Track page navigations (for SPAs or dynamic state changes)
        let lastUrl = window.location.href;
        setInterval(() => {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                window.md_e2e_record_action({ action: "NAVIGATE", url: lastUrl });
            }
        }, 500);

        function getElementSelector(el) {
            const tag = el.tagName.toLowerCase();
            
            // 1. Text for buttons/links
            if (tag === "a" || tag === "button" || el.getAttribute("role") === "button" || el.getAttribute("role") === "link") {
                const text = el.textContent ? el.textContent.trim() : "";
                if (text) return text;
            }

            // 2. Label associated with input
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${el.id}"]`);
                if (labelEl) {
                    const text = labelEl.textContent ? labelEl.textContent.trim() : "";
                    if (text) return text;
                }
            }
            const parentLabel = el.closest("label");
            if (parentLabel) {
                const text = parentLabel.textContent ? parentLabel.textContent.trim() : "";
                if (text) return text;
            }

            // 3. Placeholder attribute
            const placeholder = el.getAttribute("placeholder");
            if (placeholder) return placeholder.trim();

            // 4. Name attribute
            const name = el.getAttribute("name");
            if (name) return name.trim();

            // 5. ID attribute
            if (el.id) return `#${el.id}`;

            // 6. Value if button
            if (tag === "input" && (el.type === "submit" || el.type === "button")) {
                if (el.value) return el.value.trim();
            }

            return "";
        }

        document.addEventListener("click", function(e) {
            const el = e.target;
            const interactive = el.closest("button, a, input[type='submit'], input[type='button'], [role='button'], [role='link']");
            if (interactive) {
                const tag = interactive.tagName.toLowerCase();
                const selector = getElementSelector(interactive);
                if (selector) {
                    if (tag === "a" || interactive.getAttribute("role") === "link") {
                        window.md_e2e_record_action({ action: "CLICK_LINK", target: selector });
                    } else {
                        window.md_e2e_record_action({ action: "CLICK_BUTTON", target: selector });
                    }
                }
                return;
            }

            const checkable = el.closest("input[type='checkbox'], input[type='radio']");
            if (checkable) {
                const selector = getElementSelector(checkable);
                if (selector) {
                    const action = checkable.checked ? "CHECK" : "UNCHECK";
                    window.md_e2e_record_action({ action: action, target: selector });
                }
            }
        }, true);

        document.addEventListener("change", function(e) {
            const el = e.target;
            if (el.tagName.toLowerCase() === "select") {
                const selector = getElementSelector(el);
                const value = el.options[el.selectedIndex].text;
                if (selector && value) {
                    window.md_e2e_record_action({ action: "SELECT", target: selector, value: value });
                }
            }
        }, true);

        document.addEventListener("blur", function(e) {
            const el = e.target;
            if ((el.tagName.toLowerCase() === "input" && ["text", "email", "password", "search", "tel", "url"].includes(el.type)) || el.tagName.toLowerCase() === "textarea") {
                const selector = getElementSelector(el);
                const value = el.value;
                if (selector && value !== undefined && value !== "") {
                    window.md_e2e_record_action({ action: "FILL", target: selector, value: value });
                }
            }
        }, true);
    })();
    """

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.expose_binding("md_e2e_record_action", on_action)
        await page.add_init_script(js_recorder)

        # Setup exit future on window close/disconnect
        loop = asyncio.get_running_loop()
        exit_future = loop.create_future()

        def set_exit_result() -> None:
            if not exit_future.done():
                exit_future.set_result(None)

        page.on("close", lambda p: set_exit_result())
        browser.on("disconnected", lambda b: set_exit_result())

        # Go to starting URL
        try:
            await page.goto(url)
        except Exception as e:
            rprint(f"[red]Error loading URL: {e}[/red]")

        # Wait until browser is closed
        await exit_future

        # Save to markdown output
        out_p = Path(output_path)
        if steps:
            markdown_content = generate_markdown_spec(url, steps)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(markdown_content, encoding="utf-8")
            rprint(f"[bold green]Saved E2E test recording to: {out_p}[/bold green]")
        else:
            rprint("[yellow]No steps recorded.[/yellow]")
