#!/usr/bin/env python3
"""Local MCP server for traffic-sim — verify PostHog instrumentation from any MCP client.

Exposes three tools that wrap the CLI handlers:
- simulate_new_user
- simulate_returning_user
- check_posthog_loading

Each tool launches a Playwright browser, drives it against the given URL,
and returns a structured summary of what PostHog events fired.

Run via Claude Code's .mcp.json (invoked automatically by the MCP client):
  uv run python tools/traffic-sim/mcp_server.py
"""

from __future__ import annotations

import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

# Make the sibling cli module importable when this file is run directly
# (e.g. by `uv run python tools/traffic-sim/mcp_server.py`).
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import cli  # noqa: E402

mcp = FastMCP(
    "traffic-sim",
    instructions=(
        "Drive a real browser at a URL and verify PostHog instrumentation. "
        "Use simulate_new_user / simulate_returning_user to send traffic and "
        "watch which events fire. Use check_posthog_loading to inspect how "
        "the PostHog snippet is loaded across pages."
    ),
)


def _summarize_visits(results: list[cli.VisitResult]) -> dict[str, Any]:
    network_events: list[str] = []
    console_events: list[str] = []
    visits_with_pageview = 0
    for r in results:
        visit_network = [e for req in r.posthog_requests for e in req.events]
        visit_console = cli.extract_posthog_events_from_console(r.console_lines)
        network_events.extend(visit_network)
        console_events.extend(visit_console)
        visit_events = visit_network or visit_console
        if "$pageview" in visit_events:
            visits_with_pageview += 1
    events = network_events or console_events
    counts = Counter(events)
    success = sum(sum(1 for req in r.posthog_requests if req.status in (200, 204)) for r in results)
    requests = sum(len(r.posthog_requests) for r in results)
    errors = [r.error for r in results if r.error]
    return {
        "total_visits": len(results),
        "posthog_requests": requests,
        "posthog_requests_ok": success,
        "events_by_type": dict(sorted(counts.items())),
        "pageviews": counts.get("$pageview", 0),
        "errors": errors,
        # verified: every visit captured at least one $pageview, and none errored.
        "verified": bool(results) and visits_with_pageview == len(results) and not errors,
    }


@mcp.tool()
async def simulate_new_user(
    url: str,
    visits: int = 3,
    interval: float = 5.0,
    posthog_host: str = cli.DEFAULT_POSTHOG_HOST,
    verbose: bool = False,
) -> dict[str, Any]:
    """Send N fresh-browser visits to a URL and report which PostHog events fired.

    Each visit uses a brand-new browser context (no cookies, no localStorage),
    so this matches a stream of unique visitors.

    Args:
        url: Target URL to visit. Repeat the call to spread across multiple URLs.
        visits: Number of visits (default 3). Each visit takes ~10s plus interval.
        interval: Seconds to wait between visits (default 5).
        posthog_host: PostHog ingestion host. Defaults to https://us.i.posthog.com.
                      Set to https://eu.i.posthog.com for the EU cloud, or your
                      self-hosted host (e.g. https://ph.example.com).
        verbose: Print every PostHog request and console line to stderr.
    """
    run_id = uuid.uuid4().hex[:8]
    posthog_domains = cli.resolve_posthog_domains(posthog_host)
    results = await cli.run_new_user(
        urls=[url],
        visits=visits,
        interval=interval,
        headless=True,
        verbose=verbose,
        cloud=False,
        timeout_ms=cli.DEFAULT_TIMEOUT_MS,
        run_id=run_id,
        posthog_domains=posthog_domains,
    )
    return {"run_id": run_id, "scenario": "new-user", **_summarize_visits(results)}


@mcp.tool()
async def simulate_returning_user(
    url: str,
    page_views: int = 3,
    interval: float = 5.0,
    posthog_host: str = cli.DEFAULT_POSTHOG_HOST,
    verbose: bool = False,
) -> dict[str, Any]:
    """Send N page views from a single returning user and report which PostHog events fired.

    All page views share the same browser context, so cookies persist —
    this matches a single visitor browsing multiple pages in a session.

    Args:
        url: Target URL to visit. Repeat the call to spread across multiple URLs.
        page_views: Number of page views (default 3).
        interval: Seconds to wait between page views (default 5).
        posthog_host: PostHog ingestion host. Defaults to https://us.i.posthog.com.
        verbose: Print every PostHog request and console line to stderr.
    """
    run_id = uuid.uuid4().hex[:8]
    posthog_domains = cli.resolve_posthog_domains(posthog_host)
    results = await cli.run_returning_user(
        urls=[url],
        page_views=page_views,
        interval=interval,
        headless=True,
        verbose=verbose,
        cloud=False,
        timeout_ms=cli.DEFAULT_TIMEOUT_MS,
        run_id=run_id,
        posthog_domains=posthog_domains,
    )
    return {"run_id": run_id, "scenario": "returning-user", **_summarize_visits(results)}


@mcp.tool()
async def check_posthog_loading(
    urls: list[str],
    posthog_host: str = cli.DEFAULT_POSTHOG_HOST,
    verbose: bool = False,
) -> dict[str, Any]:
    """Inspect how the PostHog snippet is loaded on each URL.

    For each URL, returns whether posthog is detected, how it was loaded
    (head_snippet / snippet / array_js_only), the init config, and runtime
    state. Use this to confirm that all pages on a site initialize PostHog
    consistently (catches misconfigurations like a missing snippet on /pricing).

    Args:
        urls: List of target URLs to inspect.
        posthog_host: PostHog ingestion host. Defaults to https://us.i.posthog.com.
        verbose: Print extra detail per page to stderr.
    """
    if not urls:
        return {"error": "Provide at least one URL."}
    run_id = uuid.uuid4().hex[:8]
    posthog_domains = cli.resolve_posthog_domains(posthog_host)
    pages = await cli.run_check_loading(
        urls=urls,
        headless=True,
        verbose=verbose,
        cloud=False,
        timeout_ms=cli.DEFAULT_TIMEOUT_MS,
        run_id=run_id,
        posthog_domains=posthog_domains,
    )
    loaded: list[str] = []
    not_loaded: list[str] = []
    errors: list[dict[str, str]] = []
    load_methods: Counter[str] = Counter()
    for url, page in pages.items():
        if page.get("error"):
            errors.append({"url": url, "error": page["error"]})
            continue
        if page.get("runtime_state", {}).get("loaded"):
            loaded.append(url)
        else:
            not_loaded.append(url)
        load_methods[page.get("load_method", "unknown")] += 1
    summary = {
        "loaded": loaded,
        "not_loaded": not_loaded,
        "errors": errors,
        "load_methods": dict(load_methods),
    }
    return {"run_id": run_id, "summary": summary, "pages": pages}


if __name__ == "__main__":
    mcp.run()
