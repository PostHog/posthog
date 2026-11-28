"""A journey run runtime for tests: a local Chromium, a policy that allows loopback, memory storage."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from products.user_journeys.backend.logic.run_browser import BrowserOptions, BrowserPage, open_playwright_page
from products.user_journeys.backend.logic.run_screenshots import screenshot_hash
from products.user_journeys.backend.logic.run_urls import UrlPolicy
from products.user_journeys.backend.logic.runs import RunRuntime

# The sandbox ships Chromium here, without the headless shell Playwright looks for by default.
_CHROMIUM_PATH = "/opt/pw-browsers/chromium"


class AllowLoopbackPolicy:
    """Allows the 127.0.0.1 test site, which the production policy refuses by design."""

    def page_error(self, url: str) -> str | None:
        return None

    def request_error(self, url: str) -> str | None:
        return None


class MemoryScreenshotStore:
    def __init__(self) -> None:
        self.images: dict[tuple[int, str], bytes] = {}

    def put(self, team_id: int, content: bytes) -> str:
        content_hash = screenshot_hash(content)
        self.images[(team_id, content_hash)] = content
        evidence_dir = os.environ.get("JOURNEY_RUN_EVIDENCE_DIR")
        if evidence_dir:
            Path(evidence_dir).mkdir(parents=True, exist_ok=True)
            name = f"{len(list(Path(evidence_dir).iterdir())):03d}-{content_hash[:12]}.png"
            (Path(evidence_dir) / name).write_bytes(content)
        return content_hash

    def get(self, team_id: int, content_hash: str) -> bytes | None:
        return self.images.get((team_id, content_hash))

    def url(self, team_id: int, content_hash: str) -> str | None:
        return f"memory://{team_id}/{content_hash}"


@contextmanager
def local_chromium_page(options: BrowserOptions, policy: UrlPolicy) -> Iterator[BrowserPage]:
    executable = _CHROMIUM_PATH if Path(_CHROMIUM_PATH).exists() else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            with open_playwright_page(browser, options, policy) as page:
                yield page
        finally:
            browser.close()


def local_runtime(store: MemoryScreenshotStore) -> RunRuntime:
    return RunRuntime(open_page=local_chromium_page, url_policy=lambda team_id: AllowLoopbackPolicy(), store=store)
