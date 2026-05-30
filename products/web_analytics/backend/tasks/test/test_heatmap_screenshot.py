from contextlib import contextmanager
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import (
    HEATMAP_BROWSERLESS_FLAG,
    _browserless_screenshot,
    _build_browserless_screenshot_url,
    _redact_browserless_url,
    _sanitize_browserless_error,
    _use_browserless_for_screenshot,
    generate_heatmap_screenshot,
)

BROWSERLESS_SETTINGS = {
    "HEATMAP_BROWSERLESS_URL": "wss://production-sfo.browserless.io/chromium",
    "HEATMAP_BROWSERLESS_TOKEN": "secret-token",
    "HEATMAP_BROWSERLESS_TIMEOUT_MS": 180000,
    "HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS": 30000,
}


def _make_response(content: bytes = b"", status: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.text = text
    return resp


class TestHeatmapScreenshotTask(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Stub ph_scoped_capture so tests don't spin up a real PostHog client, and record the events.
        self.captured_events: list[dict] = []

        @contextmanager
        def _fake_scoped_capture():
            def _capture(**kwargs: object) -> None:
                self.captured_events.append(kwargs)

            yield _capture

        patcher = patch(
            "products.web_analytics.backend.tasks.heatmap_screenshot.ph_scoped_capture",
            _fake_scoped_capture,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_generates_multiple_width_snapshots_and_marks_completed(self, mock_sync_playwright: MagicMock) -> None:
        # Arrange Playwright mocks
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        # playwright context manager
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        # context -> page
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        # mock page behavior
        mock_page.evaluate.return_value = 1200  # total page height
        # Return different bytes per screenshot call to verify width mapping
        mock_page.screenshot.side_effect = [b"jpeg320", b"jpeg768", b"jpeg1024"]

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320, 768, 1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Act
        generate_heatmap_screenshot(heatmap.id)

        # Assert status and snapshots
        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED

        snaps = list(HeatmapSnapshot.objects.filter(heatmap=heatmap).order_by("width"))
        assert [s.width for s in snaps] == [320, 768, 1024]
        assert snaps[0].content == b"jpeg320"
        assert snaps[1].content == b"jpeg768"
        assert snaps[2].content == b"jpeg1024"

        # One launch renders every width locally
        mock_p.chromium.launch.assert_called_once()
        mock_browser.close.assert_called_once()

        # A mode-usage event is captured for the local path
        assert len(self.captured_events) == 1
        event = self.captured_events[0]
        assert event["event"] == "heatmap screenshot generated"
        assert event["properties"]["mode"] == "local"
        assert event["properties"]["success"] is True
        assert event["properties"]["width_count"] == 3
        assert event["properties"]["duration_seconds"] is not None
        assert event["groups"]["project"] == str(self.team.uuid)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_failure_marks_failed_and_records_exception(self, mock_sync_playwright: MagicMock) -> None:
        # Arrange: make playwright crash when entering context
        mock_sync_playwright.return_value.__enter__.side_effect = RuntimeError("boom")

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Act
        try:
            generate_heatmap_screenshot(heatmap.id)
        except RuntimeError:
            pass

        # Assert
        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        assert "boom" in (heatmap.exception or "")

        # A failure mode-usage event is captured
        assert self.captured_events[-1]["properties"]["success"] is False
        assert self.captured_events[-1]["properties"]["mode"] == "local"
        assert self.captured_events[-1]["properties"]["error_type"] == "RuntimeError"

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_local_path_installs_request_interception(self, mock_sync_playwright: MagicMock) -> None:
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.evaluate.return_value = 1200
        mock_page.screenshot.side_effect = [b"jpeg1024"]

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        generate_heatmap_screenshot(heatmap.id)

        mock_p.chromium.launch.assert_called_once()
        mock_page.route.assert_called()

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_snapshots_persisted_only_after_browser_closed(self, mock_sync_playwright: MagicMock) -> None:
        # Regression: Django ORM calls inside `with sync_playwright()` run in its greenlet/event-loop
        # context and raise SynchronousOnlyOperation, so persistence must happen after browser.close().
        # Mocks can't reproduce that async context, so assert the call ordering instead.
        order: list[str] = []
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.evaluate.return_value = 1200
        mock_page.screenshot.side_effect = [b"jpeg320", b"jpeg768"]
        mock_browser.close.side_effect = lambda: order.append("browser_close")

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320, 768],
            status=SavedHeatmap.Status.PROCESSING,
        )

        real_get_or_create = HeatmapSnapshot.objects.get_or_create

        def recording_get_or_create(*args: Any, **kwargs: Any) -> Any:
            order.append("persist")
            return real_get_or_create(*args, **kwargs)

        with patch.object(HeatmapSnapshot.objects, "get_or_create", side_effect=recording_get_or_create):
            generate_heatmap_screenshot(heatmap.id)

        # The browser must be closed before any snapshot is persisted
        assert order, "expected snapshots to be persisted"
        assert order[0] == "browser_close", f"snapshots persisted inside the Playwright context: {order}"

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot._use_browserless_for_screenshot", return_value=True)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_cloud_path_uses_rest_screenshot_api(
        self, mock_requests: MagicMock, mock_sync_playwright: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        mock_requests.post.return_value = _make_response(b"img1024")

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        generate_heatmap_screenshot(heatmap.id)

        # The REST path never touches local Playwright
        mock_sync_playwright.assert_not_called()

        mock_requests.post.assert_called_once()
        endpoint = mock_requests.post.call_args.args[0]
        assert "/screenshot" in endpoint
        assert "token=secret-token" in endpoint
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["url"] == "https://example.com"
        assert body["viewport"]["width"] == 1024

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED
        snaps = {s.width: s.content for s in HeatmapSnapshot.objects.filter(heatmap=heatmap)}
        assert snaps == {1024: b"img1024"}

        # The mode-usage event reflects the browserless path
        assert self.captured_events[-1]["properties"]["mode"] == "browserless"
        assert self.captured_events[-1]["properties"]["success"] is True

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot._use_browserless_for_screenshot", return_value=True)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_cloud_path_one_request_per_width(
        self, mock_requests: MagicMock, mock_sync_playwright: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        mock_requests.post.side_effect = [
            _make_response(b"img320"),
            _make_response(b"img768"),
            _make_response(b"img1024"),
        ]

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320, 768, 1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        generate_heatmap_screenshot(heatmap.id)

        # One /screenshot request per width, each carrying its own viewport width
        assert mock_requests.post.call_count == 3
        mock_sync_playwright.assert_not_called()
        bodies = [call.kwargs["json"] for call in mock_requests.post.call_args_list]
        assert [body["viewport"]["width"] for body in bodies] == [320, 768, 1024]
        # Narrow widths render as a touch/mobile viewport
        assert bodies[0]["viewport"]["isMobile"] is True
        assert bodies[2]["viewport"]["isMobile"] is False

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED
        # Each width's bytes land on the matching row (the width→image mapping must be preserved)
        snaps = {s.width: s.content for s in HeatmapSnapshot.objects.filter(heatmap=heatmap)}
        assert snaps == {320: b"img320", 768: b"img768", 1024: b"img1024"}

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot._use_browserless_for_screenshot", return_value=True)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_cloud_path_failure_on_later_width_marks_failed_and_persists_nothing(
        self, mock_requests: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        # First width succeeds, second width's request fails
        mock_requests.post.side_effect = [_make_response(b"img320"), Exception("boom on second width")]

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320, 768],
            status=SavedHeatmap.Status.PROCESSING,
        )

        with self.assertRaises(RuntimeError):
            generate_heatmap_screenshot(heatmap.id)

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        # Snapshots persist only after every width succeeds, so a later failure leaves none
        assert HeatmapSnapshot.objects.filter(heatmap=heatmap).count() == 0
        assert self.captured_events[-1]["properties"]["mode"] == "browserless"
        assert self.captured_events[-1]["properties"]["success"] is False

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch(
        "products.web_analytics.backend.tasks.heatmap_screenshot._use_browserless_for_screenshot",
        return_value=False,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_flag_off_uses_local_even_when_url_set(
        self, mock_sync_playwright: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.evaluate.return_value = 1200
        mock_page.screenshot.side_effect = [b"jpeg1024"]

        heatmap = self._make_heatmap()
        generate_heatmap_screenshot(heatmap.id)

        # Browserless configured (URL set) but flag off → local launch, and interception installed
        mock_p.chromium.launch.assert_called_once()
        mock_page.route.assert_called()

    def _make_heatmap(self) -> SavedHeatmap:
        return SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

    @override_settings(HEATMAP_BROWSERLESS_URL="")
    def test_use_browserless_false_when_url_unset(self) -> None:
        assert _use_browserless_for_screenshot(self._make_heatmap()) is False

    @override_settings(HEATMAP_BROWSERLESS_URL="wss://host/chromium", DEBUG=True)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.posthoganalytics.feature_enabled")
    def test_use_browserless_true_in_debug_without_consulting_flag(self, mock_feature_enabled: MagicMock) -> None:
        assert _use_browserless_for_screenshot(self._make_heatmap()) is True
        mock_feature_enabled.assert_not_called()

    @override_settings(HEATMAP_BROWSERLESS_URL="wss://host/chromium", DEBUG=False)
    @patch(
        "products.web_analytics.backend.tasks.heatmap_screenshot.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_use_browserless_consults_flag_with_team_groups_in_prod(self, mock_feature_enabled: MagicMock) -> None:
        assert _use_browserless_for_screenshot(self._make_heatmap()) is True
        mock_feature_enabled.assert_called_once()
        args, kwargs = mock_feature_enabled.call_args
        assert args[0] == HEATMAP_BROWSERLESS_FLAG
        # The distinct_id (2nd positional) is the per-team bucketing key — a whole team flips together
        assert args[1] == str(self.team.id)
        assert kwargs["groups"]["project"] == str(self.team.id)
        assert kwargs["groups"]["organization"] == str(self.team.organization_id)
        assert kwargs["send_feature_flag_events"] is False
        assert kwargs["only_evaluate_locally"] is False

    @override_settings(HEATMAP_BROWSERLESS_URL="wss://host/chromium", DEBUG=False)
    @patch(
        "products.web_analytics.backend.tasks.heatmap_screenshot.posthoganalytics.feature_enabled",
        side_effect=Exception("flags service down"),
    )
    def test_use_browserless_fails_closed_on_flag_error(self, mock_feature_enabled: MagicMock) -> None:
        assert _use_browserless_for_screenshot(self._make_heatmap()) is False


# Pure-function tests for the Browserless REST helper — no DB, so they run on SimpleTestCase.
class TestBrowserlessScreenshotRequest(SimpleTestCase):
    @parameterized.expand([("desktop", 1024, False), ("mobile", 320, True)])
    @override_settings(
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
        HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000,
        HEATMAP_BROWSERLESS_BLOCK_ADS=False,
        HEATMAP_BROWSERLESS_BLOCK_CONSENT_MODALS=True,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_posts_full_page_body_with_viewport_width(
        self, _name: str, width: int, is_mobile: bool, mock_requests: MagicMock
    ) -> None:
        mock_requests.post.return_value = _make_response(b"img")

        content = _browserless_screenshot("https://host/screenshot?token=t", "https://example.com", width)

        assert content == b"img"
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["url"] == "https://example.com"
        assert body["viewport"]["width"] == width
        assert body["viewport"]["isMobile"] is is_mobile
        assert body["options"]["fullPage"] is True
        assert body["options"]["type"] == "jpeg"
        assert body["scrollPage"] is True
        assert body["blockConsentModals"] is True
        assert "blockAds" not in body
        # (connect, read) timeout tuple wired from settings
        assert mock_requests.post.call_args.kwargs["timeout"] == (30.0, 210.0)

    @override_settings(
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
        HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000,
        HEATMAP_BROWSERLESS_BLOCK_ADS=True,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_block_ads_added_to_body_when_enabled(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _make_response(b"img")
        _browserless_screenshot("https://host/screenshot?token=t", "https://example.com", 1024)
        assert mock_requests.post.call_args.kwargs["json"]["blockAds"] is True

    @parameterized.expand(["non_200", "request_raises"])
    @override_settings(
        HEATMAP_BROWSERLESS_TOKEN="secret-token",
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
        HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_failure_redacts_token(self, mode: str, mock_requests: MagicMock) -> None:
        endpoint = "https://host/screenshot?token=secret-token&timeout=180000"
        if mode == "non_200":
            mock_requests.post.return_value = _make_response(b"", status=401, text="Unauthorized token=secret-token")
        else:
            mock_requests.post.side_effect = Exception("ECONNREFUSED https://host/screenshot?token=secret-token")

        with self.assertRaises(RuntimeError) as ctx:
            _browserless_screenshot(endpoint, "https://example.com", 1024)

        message = str(ctx.exception)
        # The token must never reach the (API-readable) persisted exception
        assert "secret-token" not in message
        assert "REDACTED" in message


# Pure-function tests for the Browserless URL helpers — no DB, so they run on SimpleTestCase.
class TestBrowserlessUrlHelpers(SimpleTestCase):
    @override_settings(HEATMAP_BROWSERLESS_URL="")
    def test_build_screenshot_url_returns_none_when_unset(self) -> None:
        assert _build_browserless_screenshot_url() is None

    @override_settings(
        HEATMAP_BROWSERLESS_URL="wss://production-sfo.browserless.io/chromium",
        HEATMAP_BROWSERLESS_TOKEN="t",
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
    )
    def test_build_screenshot_url_builds_https_endpoint(self) -> None:
        url = _build_browserless_screenshot_url()
        assert url is not None
        assert url.startswith("https://production-sfo.browserless.io/screenshot?")
        assert "token=t" in url
        assert "timeout=180000" in url

    @override_settings(
        HEATMAP_BROWSERLESS_URL="wss://production-sfo.browserless.io/chromium   # region nearest your worker",
        HEATMAP_BROWSERLESS_TOKEN="t",
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
    )
    def test_build_screenshot_url_strips_inline_comment_and_whitespace(self) -> None:
        # A bash-sourced .env keeps the inline comment in the value; we must not let it become a fragment.
        url = _build_browserless_screenshot_url()
        assert url is not None
        assert url.startswith("https://production-sfo.browserless.io/screenshot?")
        assert "#" not in url
        assert "region" not in url

    def test_redact_browserless_url_strips_token_and_userinfo(self) -> None:
        redacted = _redact_browserless_url("https://user:pass@host:3000/screenshot?token=supersecret&timeout=1000")
        assert "supersecret" not in redacted
        assert "pass" not in redacted
        assert "token=REDACTED" in redacted
        assert "timeout=1000" in redacted

    @override_settings(HEATMAP_BROWSERLESS_TOKEN="supersecret")
    def test_sanitize_browserless_error_scrubs_token_but_keeps_reason(self) -> None:
        msg = "Unexpected server response: 401 at https://host/screenshot?token=supersecret&timeout=180000"
        sanitized = _sanitize_browserless_error(msg)
        assert "supersecret" not in sanitized
        assert "token=REDACTED" in sanitized
        # The real failure reason is preserved so the error is debuggable
        assert "401" in sanitized
