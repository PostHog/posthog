"""The browser a journey run drives, behind a small protocol.

The executor talks only to `BrowserPage`, so production drives a remote Browserless browser over CDP
and tests drive a local Chromium, both through `open_playwright_page`, and unit tests drive a fake.
Every page this module opens routes each request through a `UrlPolicy` and starts from an empty
browser context: no cookies, no storage and no credentials of any kind.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from django.conf import settings

import structlog
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Request,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    WebSocketRoute,
    sync_playwright,
)

from posthog.dataclasses import frozen
from posthog.egress.browserless.transport import consume_browserless_session
from posthog.egress.limiter.policies import Priority

from .run_urls import UrlPolicy

logger = structlog.get_logger(__name__)

# Sized past the longest journey a run allows (`RUN_TIME_BUDGET_SECONDS`) plus connect and teardown,
# so Browserless doesn't end the session in the middle of a run.
BROWSERLESS_SESSION_TIMEOUT_MS = 240_000
BROWSERLESS_CONNECT_TIMEOUT_MS = 30_000
BROWSERLESS_SOURCE = "user_journeys_run"
# A viewport screenshot at the largest allowed viewport is far below this. Past it the image is
# not stored, so one odd page can't fill storage.
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024

_WEB_SOCKET_SCHEMES = {"ws": "http", "wss": "https"}


class BrowserUnavailableError(Exception):
    """No browser could be opened for the run. The message is safe to show to the project."""


class NavigationError(Exception):
    def __init__(self, message: str, *, timed_out: bool) -> None:
        super().__init__(message)
        self.timed_out = timed_out


@frozen
class BrowserOptions:
    viewport_width: int
    viewport_height: int
    # A run nobody is waiting on draws from the sheddable lane of the browser fleet's budget.
    background: bool


@frozen
class BlockedNavigation:
    url: str
    reason: str


class BrowserPage(Protocol):
    @property
    def url(self) -> str: ...

    def goto(self, url: str, *, timeout_ms: int) -> int | None:
        """Open `url` and return the HTTP status of the document, or None when there was no response.

        Raises `NavigationError` when the page doesn't load.
        """
        ...

    def wait_for_settled(self, *, timeout_ms: int) -> None:
        """Wait until the network is idle, or until `timeout_ms` passes. Never raises for the timeout."""
        ...

    def wait(self, ms: int) -> None: ...

    def evaluate(self, script: str, arg: object) -> object:
        """Run `script` in the page as a function of `arg`. Values reach the page only through `arg`."""
        ...

    def screenshot(self) -> bytes | None:
        """A PNG of the viewport, or None when the image is too large to keep."""
        ...

    def click(self, x: float, y: float) -> None: ...

    def take_blocked_navigation(self) -> BlockedNavigation | None:
        """The last main-frame navigation the URL policy refused since the previous call, if any."""
        ...


BrowserSessionFactory = Callable[[BrowserOptions, UrlPolicy], AbstractContextManager[BrowserPage]]


class PlaywrightPage:
    def __init__(self, context: BrowserContext, page: Page, policy: UrlPolicy) -> None:
        self._context = context
        self._page = page
        self._policy = policy
        self._blocked: BlockedNavigation | None = None
        context.route("**/*", self._route_request)
        context.route_web_socket(re.compile(".*"), self._route_web_socket)
        # Chromium follows a server redirect without passing the new URL through the routes above, so
        # every response is paused before it is read and a redirect is checked against the policy.
        self._cdp = context.new_cdp_session(page)
        self._main_frame_id: str = self._cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self._cdp.on("Fetch.requestPaused", self._check_redirect)
        self._cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]})
        # A journey runs in one tab. A click that opens another one would leave the run on a page
        # nobody checks, so new tabs close at once and the next step sees the original page.
        context.on("page", self._close_extra_page)

    def _close_extra_page(self, page: Page) -> None:
        if page is not self._page:
            try:
                page.close()
            except PlaywrightError:
                pass

    def _route_request(self, route: Route, request: Request) -> None:
        url = request.url
        try:
            is_page = request.is_navigation_request() and request.frame.parent_frame is None
        except PlaywrightError:
            is_page = False
        error = self._policy.page_error(url) if is_page else self._policy.request_error(url)
        if error is None:
            route.continue_()
            return
        if is_page:
            self._blocked = BlockedNavigation(url=url, reason=error)
        logger.info("user_journeys.run_request_blocked", is_page=is_page, host=urlsplit(url).hostname)
        route.abort("blockedbyclient")

    def _check_redirect(self, event: dict[str, Any]) -> None:
        status = event.get("responseStatusCode")
        location = next(
            (
                header.get("value", "")
                for header in event.get("responseHeaders") or []
                if str(header.get("name", "")).lower() == "location"
            ),
            None,
        )
        error = None
        if isinstance(status, int) and 300 <= status < 400 and location:
            target = urljoin(event["request"]["url"], location)
            is_page = event.get("resourceType") == "Document" and event.get("frameId") == self._main_frame_id
            error = self._policy.page_error(target) if is_page else self._policy.request_error(target)
            if error is not None:
                if is_page:
                    self._blocked = BlockedNavigation(url=target, reason=error)
                logger.info("user_journeys.run_redirect_blocked", is_page=is_page, host=urlsplit(target).hostname)
        try:
            if error is None:
                self._cdp.send("Fetch.continueResponse", {"requestId": event["requestId"]})
            else:
                self._cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})
        except PlaywrightError:
            # The request was cancelled while it was paused, so there is nothing left to release.
            pass

    def _route_web_socket(self, ws: WebSocketRoute) -> None:
        parts = urlsplit(ws.url)
        checked = urlunsplit((_WEB_SOCKET_SCHEMES.get(parts.scheme, parts.scheme), *parts[1:]))
        if self._policy.request_error(checked) is not None:
            ws.close()
            return
        ws.connect_to_server()

    @property
    def url(self) -> str:
        return self._page.url

    def goto(self, url: str, *, timeout_ms: int) -> int | None:
        try:
            response = self._page.goto(url, wait_until="load", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            raise NavigationError("The page didn't finish loading in time.", timed_out=True) from None
        except PlaywrightError as e:
            raise NavigationError(_short_playwright_message(e), timed_out=False) from None
        return response.status if response is not None else None

    def wait_for_settled(self, *, timeout_ms: int) -> None:
        try:
            self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            # Pages that poll or stream never reach network idle, and are still fine to check.
            pass

    def wait(self, ms: int) -> None:
        self._page.wait_for_timeout(ms)

    def evaluate(self, script: str, arg: object) -> object:
        return self._page.evaluate(script, arg)

    def screenshot(self) -> bytes | None:
        image = self._page.screenshot(type="png", full_page=False, animations="disabled", caret="hide")
        if len(image) > MAX_SCREENSHOT_BYTES:
            logger.warning("user_journeys.run_screenshot_too_large", size=len(image))
            return None
        return image

    def click(self, x: float, y: float) -> None:
        self._page.mouse.click(x, y)

    def take_blocked_navigation(self) -> BlockedNavigation | None:
        blocked, self._blocked = self._blocked, None
        return blocked


def _short_playwright_message(error: PlaywrightError) -> str:
    # Playwright appends a multi-line call log after the first line, which names internal details.
    first_line = (error.message or "").strip().splitlines()[0] if error.message else ""
    return f"The page didn't load ({first_line[:200]})." if first_line else "The page didn't load."


@contextmanager
def open_playwright_page(browser: Browser, options: BrowserOptions, policy: UrlPolicy) -> Iterator[PlaywrightPage]:
    context = browser.new_context(
        viewport={"width": options.viewport_width, "height": options.viewport_height},
        device_scale_factor=1,
        reduced_motion="reduce",
        color_scheme="light",
        locale="en-US",
        timezone_id="UTC",
        # Requests a service worker makes skip the request routes, so a worker could reach hosts the
        # URL policy refuses.
        service_workers="block",
        accept_downloads=False,
    )
    try:
        page = context.new_page()
        yield PlaywrightPage(context, page, policy)
    finally:
        try:
            context.close()
        except PlaywrightError:
            pass


def _browserless_endpoint(cdp_url: str, token: str) -> str:
    parsed = urlsplit(cdp_url)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "token"}
    if token:
        query["token"] = token
    query["timeout"] = str(BROWSERLESS_SESSION_TIMEOUT_MS)
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _redact(message: str, token: str) -> str:
    return message.replace(token, "REDACTED") if token else message


@contextmanager
def browserless_page(options: BrowserOptions, policy: UrlPolicy) -> Iterator[BrowserPage]:
    """A page on the Browserless fleet that `USER_JOURNEYS_BROWSERLESS_CDP_URL` names."""
    cdp_url = settings.USER_JOURNEYS_BROWSERLESS_CDP_URL.split("#", 1)[0].strip()
    token = settings.USER_JOURNEYS_BROWSERLESS_TOKEN
    if not cdp_url:
        raise BrowserUnavailableError("Journey runs aren't set up on this PostHog instance.")
    priority = Priority.BATCH if options.background else Priority.NORMAL
    if not consume_browserless_session(cdp_url, token, priority=priority, source=BROWSERLESS_SOURCE):
        raise BrowserUnavailableError("All browsers are busy. Try the run again in a few minutes.")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(
                _browserless_endpoint(cdp_url, token), timeout=BROWSERLESS_CONNECT_TIMEOUT_MS
            )
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            logger.warning("user_journeys.browserless_connect_failed", error=_redact(str(e), token)[:500])
            raise BrowserUnavailableError(
                "Couldn't connect to a browser. Try the run again in a few minutes."
            ) from None
        try:
            with open_playwright_page(browser, options, policy) as page:
                yield page
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass
