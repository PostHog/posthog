"""End-to-end integration test: spin up a local fixture page with a stub
PostHog snippet, run check-loading against it, and assert the snippet was
detected. Skipped automatically when Playwright isn't installed.
"""

from __future__ import annotations

import asyncio
import threading
import http.server
import socketserver

import pytest

playwright = pytest.importorskip(
    "playwright.async_api",
    reason="Playwright not installed; run `playwright install chromium` first.",
)

import cli  # noqa: E402

FIXTURE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>traffic-sim fixture</title>
  <script id="posthog-init">
    // Stub posthog object so the detector reports loaded=true without
    // hitting the network during tests.
    window.posthog = {
      __loaded: true,
      config: {token: 'phc_test_fixture', api_host: 'https://example.com'},
      get_distinct_id: function() { return 'test-distinct-id'; },
    };
  </script>
</head>
<body>
  <h1>Hello from the fixture</h1>
</body>
</html>
"""


@pytest.fixture
def fixture_server(tmp_path):
    """Serve FIXTURE_HTML on a localhost port. Yields the URL."""
    fixture_dir = tmp_path / "site"
    fixture_dir.mkdir()
    (fixture_dir / "index.html").write_text(FIXTURE_HTML)

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(fixture_dir), **kw)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.integration
def test_check_loading_detects_stubbed_posthog(fixture_server):
    """check-loading against a fixture page reports posthog as loaded."""
    pages = asyncio.run(
        cli.run_check_loading(
            urls=[fixture_server],
            headless=True,
            verbose=False,
            cloud=False,
            timeout_ms=30_000,
            run_id="itest",
            posthog_domains=cli.DEFAULT_POSTHOG_DOMAINS,
        )
    )
    assert len(pages) == 1
    page_data = next(iter(pages.values()))
    assert page_data.get("error") is None
    assert page_data["runtime_state"]["loaded"] is True
    # The stub uses #posthog-init script tag, which we treat as head_snippet.
    assert page_data["load_method"] == "head_snippet"
    assert page_data["init_config"]["api_key"] == "phc_test_fixture"
