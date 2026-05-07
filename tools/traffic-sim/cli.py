#!/usr/bin/env python3
# ruff: noqa: T201
"""Drive a real browser at a URL and verify PostHog instrumentation.

Three scenarios:
  new-user        Each visit uses a fresh browser context (no cookies).
  returning-user  All page views share the same context (cookies persist).
  check-loading   Inspect how the PostHog snippet is loaded across pages.

Optional cloud runner (`--cloud`) uses BrowserStack and reports the
verification result back to the BrowserStack session. Requires the
browserstack-sdk dependency to be installed.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import uuid
import random
import asyncio
import argparse
import urllib.parse
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

DEFAULT_TIMEOUT_MS = 120_000
DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
DEFAULT_POSTHOG_DOMAINS = ("posthog.com", "i.posthog.com")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

RESULTS_DIR = Path(__file__).parent / "results"


# Detects PostHog presence and configuration on a page. Returns a dict shaped
# like {loaded, load_method, init_config, runtime_state, ...}.
POSTHOG_DETECT_JS = r"""
() => {
    const scripts = [...document.querySelectorAll('script')];
    const posthogScripts = scripts.filter(s => {
        const src = (s.src || '').toLowerCase();
        const id = (s.id || '').toLowerCase();
        const text = (s.textContent || '').toLowerCase();
        return src.includes('posthog') || src.includes('array.js') ||
               id.includes('posthog') || text.includes('posthog') ||
               text.includes('phc_') || text.includes('ph_init');
    });
    const hasPosthogInitId = !!document.getElementById('posthog-init');
    const snippetPattern = /!function\s*\([a-z],[a-z]\)\s*\{[^}]*__SV/;
    let hasWebSnippet = false;
    let snippetLocation = null;
    for (const s of posthogScripts) {
        if (snippetPattern.test(s.textContent || '')) {
            hasWebSnippet = true;
            snippetLocation = s.parentElement ? s.parentElement.tagName.toLowerCase() : null;
            break;
        }
    }
    let initConfig = null;
    for (const s of posthogScripts) {
        const text = s.textContent || '';
        const m = text.match(/posthog\.init\s*\(\s*['"]([^'"]+)['"]\s*,\s*(\{[\s\S]*?\})\s*\)/);
        if (m) {
            try {
                const raw = m[2].replace(/(\w+)\s*:/g, '"$1":').replace(/'/g, '"').replace(/,\s*}/g, '}');
                const p = JSON.parse(raw);
                initConfig = {
                    api_key: m[1],
                    api_host: p.api_host || null,
                    person_profiles: p.person_profiles || null,
                };
            } catch (e) {
                initConfig = {api_key: m[1]};
            }
            break;
        }
    }
    if (!initConfig && window.posthog && window.posthog.config) {
        const c = window.posthog.config;
        initConfig = {
            api_key: c.token || null,
            api_host: c.api_host || null,
            person_profiles: c.person_profiles || null,
        };
    }
    const arrScript = posthogScripts.find(s => s.src && s.src.includes('array'));
    const defined = typeof window.posthog !== 'undefined';
    const runtimeState = defined && window.posthog
        ? {
            defined: true,
            loaded: !!window.posthog.__loaded,
            distinct_id: window.posthog.get_distinct_id ? window.posthog.get_distinct_id() : null,
            config_api_host: window.posthog.config ? window.posthog.config.api_host : null,
        }
        : {defined: false, loaded: false};
    let loadMethod = 'none';
    if (runtimeState.loaded && hasPosthogInitId) loadMethod = 'head_snippet';
    else if (runtimeState.loaded && hasWebSnippet) loadMethod = 'snippet';
    else if (runtimeState.loaded && arrScript) loadMethod = 'array_js_only';
    else if (runtimeState.loaded) loadMethod = 'unknown';
    return {
        loaded: runtimeState.loaded,
        load_method: loadMethod,
        has_posthog_init_id: hasPosthogInitId,
        has_web_snippet: hasWebSnippet,
        snippet_location: snippetLocation,
        array_js_src: arrScript ? arrScript.src : null,
        script_tag_count: posthogScripts.length,
        init_config: initConfig,
        runtime_state: runtimeState,
    };
}
"""


@dataclass
class AnalyticsRequest:
    timestamp: str
    url: str
    method: str
    status: int | None = None
    events: list[str] = field(default_factory=list)


@dataclass
class ConsoleLine:
    timestamp: str
    type: str
    text: str
    is_posthog: bool = False


@dataclass
class VisitResult:
    visit_number: int
    scenario: str
    url: str
    timestamp: str
    page_load_ms: float | None = None
    posthog_requests: list[AnalyticsRequest] = field(default_factory=list)
    console_lines: list[ConsoleLine] = field(default_factory=list)
    error: str | None = None


class AnalyticsCapture:
    """Captures PostHog network requests and console output from a page."""

    def __init__(self, posthog_domains: tuple[str, ...], verbose: bool = False):
        self.posthog_domains = posthog_domains
        self.verbose = verbose
        self.posthog_requests: list[AnalyticsRequest] = []
        self.console_lines: list[ConsoleLine] = []
        # Keyed by id(request) so concurrent in-flight requests to the same
        # URL (e.g. successive /batch/ flushes) don't overwrite each other.
        self._pending: dict[int, AnalyticsRequest] = {}

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("console", self._on_console)

    def _is_posthog(self, url: str) -> bool:
        # Match on parsed hostname rather than substring so URLs that merely
        # contain a PostHog domain in their path (e.g. an open-redirect) are
        # not misclassified as PostHog ingestion traffic.
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        return any(host == d or host.endswith("." + d) for d in self.posthog_domains)

    def _on_request(self, request) -> None:
        if not self._is_posthog(request.url):
            return
        req = AnalyticsRequest(
            timestamp=datetime.now(UTC).isoformat(),
            url=request.url,
            method=request.method,
        )
        if request.post_data:
            try:
                data = json.loads(request.post_data)
                if isinstance(data, dict) and "batch" in data:
                    req.events = [e.get("event", "unknown") for e in data["batch"]]
                elif isinstance(data, dict) and "event" in data:
                    req.events = [data["event"]]
            except (json.JSONDecodeError, TypeError):
                pass
        self._pending[id(request)] = req
        if self.verbose:
            tags = ", ".join(req.events) or "unknown"
            print(f"    [PostHog] {request.method} {_short_url(request.url)} events=[{tags}]")

    def _on_response(self, response) -> None:
        if not self._is_posthog(response.url):
            return
        req = self._pending.pop(id(response.request), None)
        if req is None:
            return
        req.status = response.status
        self.posthog_requests.append(req)
        if self.verbose:
            marker = "✓" if response.status in (200, 204) else "✗"
            print(f"    [PostHog] {marker} {response.status} {_short_url(response.url)}")

    def _on_console(self, msg) -> None:
        text = msg.text
        is_posthog = "posthog" in text.lower() or "[PostHog]" in text
        line = ConsoleLine(
            timestamp=datetime.now(UTC).isoformat(),
            type=msg.type,
            text=text,
            is_posthog=is_posthog,
        )
        self.console_lines.append(line)
        if self.verbose and is_posthog:
            print(f"    [Console] {text[:100]}{'…' if len(text) > 100 else ''}")


def _short_url(url: str, max_len: int = 60) -> str:
    return url if len(url) <= max_len else url[: max_len - 1] + "…"


def _redact_api_key(value: str | None) -> str:
    # PostHog project tokens are public by design, but CodeQL flags raw-token
    # logging via `py/clear-text-logging-sensitive-data`. Render a fixed
    # placeholder instead so log output reflects only whether a token is set.
    return "set" if value else "none"


def extract_posthog_events_from_console(lines: list[ConsoleLine]) -> list[str]:
    pattern = re.compile(r'\[PostHog\.js\] send "(\$?\w+)"')
    return [m.group(1) for line in lines if line.is_posthog for m in pattern.finditer(line.text)]


def add_tracking_params(url: str, run_id: str, scenario: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params["__posthog_debug"] = ["true"]
    params["run_id"] = [run_id]
    params["scenario"] = [scenario]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


async def simulate_user_behavior(page: Page) -> None:
    await asyncio.sleep(random.uniform(1.0, 2.0))
    for _ in range(random.randint(2, 4)):
        await page.evaluate(f"window.scrollBy(0, {random.randint(100, 400)})")
        await asyncio.sleep(random.uniform(0.3, 0.8))
    await asyncio.sleep(random.uniform(1.0, 3.0))


# ---- BrowserStack (optional --cloud) ------------------------------------------


def _load_browserstack_yaml() -> tuple[str | None, str | None]:
    # Falls back to browserstack.yml next to this file (matches the shipped
    # browserstack.yml.example). Env vars take precedence; YAML is the
    # documented file-based path. Parsed manually to avoid a PyYAML dep.
    yml_path = Path(__file__).parent / "browserstack.yml"
    if not yml_path.exists():
        return None, None
    username: str | None = None
    access_key: str | None = None
    try:
        for raw in yml_path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.strip().strip('"').strip("'")
            if key.strip() == "userName":
                username = value or None
            elif key.strip() == "accessKey":
                access_key = value or None
    except OSError:
        return None, None
    return username, access_key


def _build_browserstack_cdp_url() -> str:
    username = os.environ.get("BROWSERSTACK_USERNAME")
    access_key = os.environ.get("BROWSERSTACK_ACCESS_KEY")
    if not username or not access_key:
        yml_user, yml_key = _load_browserstack_yaml()
        username = username or yml_user
        access_key = access_key or yml_key
    if not username or not access_key:
        raise RuntimeError(
            "--cloud requires BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY env vars, "
            "or a browserstack.yml file with userName/accessKey next to cli.py"
        )
    try:
        import playwright  # type: ignore[import-untyped]

        pw_version = getattr(playwright, "__version__", "1.54.0")
    except Exception:
        pw_version = "1.54.0"
    caps = {
        "browser": "chrome",
        "browser_version": "latest",
        "os": "Windows",
        "os_version": "11",
        "name": "PostHog instrumentation check",
        "build": f"traffic-sim-{datetime.now().strftime('%Y%m%d-%H%M')}",
        "browserstack.username": username,
        "browserstack.accessKey": access_key,
        "browserstack.playwrightVersion": pw_version,
        "browserstack.debug": "true",
        "browserstack.networkLogs": "true",
        "browserstack.consoleLogs": "info",
    }
    return f"wss://cdp.browserstack.com/playwright?caps={urllib.parse.quote(json.dumps(caps))}"


async def _annotate_browserstack(page: Page, text: str, level: str = "info") -> None:
    payload = json.dumps({"action": "annotate", "arguments": {"data": text, "level": level}})
    await page.evaluate("_ => {}", f"browserstack_executor: {payload}")


async def _set_browserstack_status(page: Page, passed: bool, reason: str = "") -> None:
    status = "passed" if passed else "failed"
    payload = json.dumps({"action": "setSessionStatus", "arguments": {"status": status, "reason": reason}})
    await page.evaluate("_ => {}", f"browserstack_executor: {payload}")


async def _report_cloud(page: Page, capture: AnalyticsCapture) -> None:
    events = extract_posthog_events_from_console(capture.console_lines)
    counts = Counter(events)
    pageviews = counts.get("$pageview", 0)
    breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"
    await _annotate_browserstack(page, f"PostHog events — {breakdown}")
    passed = pageviews > 0
    reason = f"{pageviews} $pageview event(s)" if passed else "no $pageview events"
    await _set_browserstack_status(page, passed, reason)


# ---- Browser setup -------------------------------------------------------------


async def _launch(p, *, cloud: bool, headless: bool) -> Browser:
    if cloud:
        return await p.chromium.connect(_build_browserstack_cdp_url())
    return await p.chromium.launch(headless=headless)


async def _new_context(browser: Browser) -> BrowserContext:
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
    )
    # Strip the webdriver flag so SPAs that look at navigator.webdriver
    # don't suppress events on us.
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
    return context


# ---- Scenarios -----------------------------------------------------------------


async def run_new_user(
    *,
    urls: list[str],
    visits: int,
    interval: float,
    headless: bool,
    verbose: bool,
    cloud: bool,
    timeout_ms: int,
    run_id: str,
    posthog_domains: tuple[str, ...],
) -> list[VisitResult]:
    results: list[VisitResult] = []
    async with async_playwright() as p:
        browser = await _launch(p, cloud=cloud, headless=headless)
        try:
            for i in range(visits):
                url = add_tracking_params(random.choice(urls), run_id, "new-user")
                result = await _do_visit(
                    browser=browser,
                    url=url,
                    visit_number=i + 1,
                    scenario="new-user",
                    fresh_context=True,
                    verbose=verbose,
                    cloud=cloud,
                    timeout_ms=timeout_ms,
                    posthog_domains=posthog_domains,
                )
                results.append(result)
                _print_visit_summary(result)
                if i < visits - 1:
                    print(f"  Waiting {interval}s before next visit…")
                    await asyncio.sleep(interval)
        finally:
            await browser.close()
    return results


async def run_returning_user(
    *,
    urls: list[str],
    page_views: int,
    interval: float,
    headless: bool,
    verbose: bool,
    cloud: bool,
    timeout_ms: int,
    run_id: str,
    posthog_domains: tuple[str, ...],
) -> list[VisitResult]:
    results: list[VisitResult] = []
    async with async_playwright() as p:
        browser = await _launch(p, cloud=cloud, headless=headless)
        context = await _new_context(browser)
        try:
            for i in range(page_views):
                url = add_tracking_params(random.choice(urls), run_id, "returning-user")
                result = await _do_visit(
                    browser=browser,
                    url=url,
                    visit_number=i + 1,
                    scenario="returning-user",
                    fresh_context=False,
                    shared_context=context,
                    verbose=verbose,
                    cloud=cloud,
                    timeout_ms=timeout_ms,
                    posthog_domains=posthog_domains,
                )
                results.append(result)
                _print_visit_summary(result)
                if i < page_views - 1:
                    print(f"  Waiting {interval}s before next page view…")
                    await asyncio.sleep(interval)
        finally:
            await context.close()
            await browser.close()
    return results


async def _do_visit(
    *,
    browser: Browser,
    url: str,
    visit_number: int,
    scenario: str,
    fresh_context: bool,
    verbose: bool,
    cloud: bool,
    timeout_ms: int,
    posthog_domains: tuple[str, ...],
    shared_context: BrowserContext | None = None,
) -> VisitResult:
    timestamp = datetime.now(UTC).isoformat()
    parsed = urlparse(url)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {scenario} {visit_number} | {parsed.netloc}{parsed.path}")
    result = VisitResult(visit_number=visit_number, scenario=scenario, url=url, timestamp=timestamp)
    context = await _new_context(browser) if fresh_context else shared_context
    assert context is not None
    page: Page | None = None
    try:
        page = await context.new_page()
        capture = AnalyticsCapture(posthog_domains=posthog_domains, verbose=verbose)
        capture.attach(page)
        start = time.perf_counter()
        await page.goto(url, wait_until="load", timeout=timeout_ms)
        result.page_load_ms = (time.perf_counter() - start) * 1000
        await asyncio.sleep(5.0)
        await simulate_user_behavior(page)
        await asyncio.sleep(3.0)
        result.posthog_requests = capture.posthog_requests
        result.console_lines = capture.console_lines
        if cloud:
            await _report_cloud(page, capture)
    except Exception as exc:
        result.error = str(exc)
        print(f"  Error: {exc}")
        if cloud and page is not None:
            try:
                await _set_browserstack_status(page, False, str(exc))
            except Exception:
                pass
    finally:
        if fresh_context:
            try:
                await context.close()
            except Exception:
                pass
        elif page is not None:
            try:
                await page.close()
            except Exception:
                pass
    return result


async def run_check_loading(
    *,
    urls: list[str],
    headless: bool,
    verbose: bool,
    cloud: bool,
    timeout_ms: int,
    run_id: str,
    posthog_domains: tuple[str, ...],
) -> dict[str, dict]:
    pages: dict[str, dict] = {}
    async with async_playwright() as p:
        browser = await _launch(p, cloud=cloud, headless=headless)
        context = await _new_context(browser)
        try:
            for i, url in enumerate(urls):
                parsed = urlparse(url)
                short = f"{parsed.hostname}{parsed.path}" if parsed.hostname else parsed.path or "/"
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ({i + 1}/{len(urls)}) {short}")
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="load", timeout=timeout_ms)
                    await asyncio.sleep(5.0)
                    detection = await page.evaluate(POSTHOG_DETECT_JS)
                    detection["url"] = url
                    detection["error"] = None
                    pages[url] = detection
                    loaded = detection.get("runtime_state", {}).get("loaded", False)
                    if verbose:
                        cfg = detection.get("init_config") or {}
                        print(
                            f"  loaded={loaded} method={detection['load_method']} "
                            f"snippet_in={detection.get('snippet_location') or '-'} "
                            f"api_key={_redact_api_key(cfg.get('api_key'))} api_host={cfg.get('api_host', 'none')}"
                        )
                    else:
                        marker = "✓" if loaded else "✗"
                        print(f"  {marker} method={detection['load_method']}")
                except Exception as exc:
                    pages[url] = {"url": url, "error": str(exc)}
                    print(f"  Error: {exc}")
                finally:
                    await page.close()
        finally:
            await context.close()
            await browser.close()
    _print_check_loading_table(pages)
    return pages


def _print_check_loading_table(pages: dict[str, dict]) -> None:
    print()
    print("=" * 100)
    print("POSTHOG LOADING")
    print("=" * 100)
    print(f"{'URL':<55} {'Loaded':<8} {'Method':<14} {'Snippet In':<12} {'API key':<14}")
    print("-" * 100)
    for url, data in pages.items():
        label = url if len(url) <= 55 else url[:54] + "…"
        if data.get("error"):
            print(f"{label:<55} ERROR    {data['error'][:40]}")
            continue
        loaded = "yes" if data.get("runtime_state", {}).get("loaded", False) else "no"
        method = data.get("load_method", "-")
        snip = data.get("snippet_location") or "-"
        cfg = data.get("init_config") or {}
        key = _redact_api_key(cfg.get("api_key"))
        print(f"{label:<55} {loaded:<8} {method:<14} {snip:<12} {key:<14}")


# ---- Output --------------------------------------------------------------------


def _print_visit_summary(result: VisitResult) -> None:
    load = f"{result.page_load_ms:.0f}ms" if result.page_load_ms else "n/a"
    network_events = [e for r in result.posthog_requests for e in r.events]
    events = network_events or extract_posthog_events_from_console(result.console_lines)
    counts = Counter(events)
    breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"
    success = sum(1 for r in result.posthog_requests if r.status in (200, 204))
    print(f"  Page load: {load}")
    print(f"  PostHog requests: {len(result.posthog_requests)} ({success} OK)")
    print(f"  PostHog events: {breakdown}")
    if result.error:
        print(f"  Error: {result.error}")


def _summary_dict(results: list[VisitResult]) -> dict:
    return {
        "posthog_requests": sum(len(r.posthog_requests) for r in results),
        "posthog_requests_ok": sum(sum(1 for req in r.posthog_requests if req.status in (200, 204)) for r in results),
        "errors": sum(1 for r in results if r.error),
    }


def _save_visits(results: list[VisitResult], scenario: str, run_id: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    filename = RESULTS_DIR / f"{scenario}_{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data = {
        "run_id": run_id,
        "scenario": scenario,
        "timestamp": datetime.now(UTC).isoformat(),
        "total_visits": len(results),
        "summary": _summary_dict(results),
        "visits": [asdict(r) for r in results],
    }
    filename.write_text(json.dumps(data, indent=2))
    print(f"\nResults saved to: {filename}")
    return filename


def _save_check_loading_report(pages: dict[str, dict], run_id: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    filename = RESULTS_DIR / f"check-loading_{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "total_urls": len(pages),
        "pages": pages,
    }
    filename.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved to: {filename}")
    return filename


# ---- URL loading ---------------------------------------------------------------


def load_urls(urls_arg: list[str] | None, urls_file: str | None) -> list[str]:
    if urls_arg:
        return urls_arg
    if urls_file:
        return _load_urls_file(urls_file)
    raise ValueError("Provide either --url <URL> ... or --urls-file <PATH>")


def _load_urls_file(path: str) -> list[str]:
    """Load URLs from a JSON file. Two accepted shapes:
    1) flat list: ["https://example.com/", ...]
    2) grouped: {"base_url": "...", "categories": {"cat": ["/path", ...]}, "extra_urls": [...]}
    """
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        if not data:
            raise ValueError(f"No URLs found in {path}")
        return data
    base = (data.get("base_url") or "").rstrip("/")
    urls: list[str] = []
    for paths in data.get("categories", {}).values():
        urls.extend(f"{base}{p}" for p in paths)
    urls.extend(data.get("extra_urls", []))
    if not urls:
        raise ValueError(f"No URLs found in {path}")
    return urls


def resolve_posthog_domains(host: str) -> tuple[str, ...]:
    """Build the set of hostnames we treat as PostHog network traffic.

    Always includes the cloud defaults (posthog.com / i.posthog.com) so events
    sent to the PostHog cloud are caught even when --posthog-host points at
    a custom reverse proxy.
    """
    extras: tuple[str, ...] = ()
    if host:
        netloc = (urlparse(host).hostname or host).lower()
        if netloc and not any(netloc == d or netloc.endswith("." + d) for d in DEFAULT_POSTHOG_DOMAINS):
            extras = (netloc,)
    return DEFAULT_POSTHOG_DOMAINS + extras


# ---- CLI -----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="traffic-sim",
        description="Drive a real browser at a URL and verify PostHog instrumentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  traffic-sim new-user --url https://example.com --visits 3
  traffic-sim returning-user --url https://example.com --page-views 5
  traffic-sim check-loading --urls-file urls.json
""",
    )
    sub = parser.add_subparsers(dest="scenario", required=True)

    nu = sub.add_parser("new-user", help="Each visit uses a fresh browser context.")
    nu.add_argument("--visits", type=int, default=10)
    nu.add_argument("--interval", type=float, default=60.0)

    ru = sub.add_parser("returning-user", help="All page views share the same browser context.")
    ru.add_argument("--page-views", type=int, default=5)
    ru.add_argument("--interval", type=float, default=30.0)

    cl = sub.add_parser("check-loading", help="Inspect how the PostHog snippet is loaded.")

    for s in (nu, ru, cl):
        s.add_argument(
            "--url",
            action="append",
            dest="urls",
            default=None,
            help="Target URL (repeatable). Mutually exclusive with --urls-file.",
        )
        s.add_argument(
            "--urls-file",
            type=str,
            default=None,
            help="JSON file of URLs (flat list or {base_url, categories} object).",
        )
        s.add_argument(
            "--posthog-host",
            type=str,
            default=DEFAULT_POSTHOG_HOST,
            help=f"PostHog ingestion host (default: {DEFAULT_POSTHOG_HOST}).",
        )
        s.add_argument(
            "--cloud",
            action="store_true",
            help="Run on BrowserStack (requires BROWSERSTACK_USERNAME/ACCESS_KEY env vars).",
        )
        s.add_argument("--headed", action="store_true", help="Show browser window (default: headless).")
        s.add_argument("--verbose", action="store_true", help="Print every PostHog request and console line.")
        s.add_argument("--timeout", type=int, default=120, help="Page load timeout in seconds (default: 120).")

    return parser


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    headless = not args.headed
    timeout_ms = args.timeout * 1000
    run_id = uuid.uuid4().hex[:8]
    urls = load_urls(args.urls, args.urls_file)
    posthog_domains = resolve_posthog_domains(args.posthog_host)

    print("PostHog Traffic Simulation")
    print(f"Scenario: {args.scenario}")
    print(f"Run ID: {run_id}")
    print(f"URLs: {len(urls)}")
    print(f"PostHog host: {args.posthog_host}")
    print(f"Headless: {headless}")
    print("=" * 60)

    if args.scenario == "check-loading":
        pages = await run_check_loading(
            urls=urls,
            headless=headless,
            verbose=args.verbose,
            cloud=args.cloud,
            timeout_ms=timeout_ms,
            run_id=run_id,
            posthog_domains=posthog_domains,
        )
        _save_check_loading_report(pages, run_id)
        return 0

    if args.scenario == "new-user":
        results = await run_new_user(
            urls=urls,
            visits=args.visits,
            interval=args.interval,
            headless=headless,
            verbose=args.verbose,
            cloud=args.cloud,
            timeout_ms=timeout_ms,
            run_id=run_id,
            posthog_domains=posthog_domains,
        )
    else:
        results = await run_returning_user(
            urls=urls,
            page_views=args.page_views,
            interval=args.interval,
            headless=headless,
            verbose=args.verbose,
            cloud=args.cloud,
            timeout_ms=timeout_ms,
            run_id=run_id,
            posthog_domains=posthog_domains,
        )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    summary = _summary_dict(results)
    print(f"Run ID: {run_id}")
    print(f"Total visits: {len(results)}")
    print(f"PostHog requests: {summary['posthog_requests']} ({summary['posthog_requests_ok']} OK)")
    print(f"Errors: {summary['errors']}")
    _save_visits(results, args.scenario, run_id)
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
