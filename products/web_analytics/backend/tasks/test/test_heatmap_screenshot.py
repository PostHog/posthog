from contextlib import contextmanager
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized
from prometheus_client import REGISTRY

from products.web_analytics.backend.api.heatmaps_utils import MAX_TARGET_WIDTHS
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import (
    HEATMAP_SCREENSHOT_STUCK_SAMPLE_SIZE,
    HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS,
    BrowserlessError,
    BrowserlessPermanentError,
    BrowserlessTransientError,
    _browserless_screenshot,
    _build_browserless_screenshot_url,
    _classify_failure,
    _redact_browserless_url,
    _resolve_widths,
    _sanitize_browserless_error,
    generate_heatmap_screenshot,
    report_stuck_heatmap_screenshots,
)

BROWSERLESS_SETTINGS = {
    "HEATMAP_BROWSERLESS_URL": "wss://production-sfo.browserless.io/chromium",
    "HEATMAP_BROWSERLESS_TOKEN": "secret-token",
    "HEATMAP_BROWSERLESS_TIMEOUT_MS": 180000,
    "HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS": 30000,
}


def _jpeg(suffix: bytes = b"") -> bytes:
    # Minimal bytes that pass the JPEG start-of-image magic-byte check.
    return b"\xff\xd8\xff" + suffix


def _make_response(
    content: bytes | None = None,
    status: int = 200,
    text: str = "",
    content_type: str = "image/jpeg",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = _jpeg() if content is None else content
    resp.text = text
    resp.headers = {"content-type": content_type}
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

    def _make_heatmap(self, target_widths: list[int] | None = None, block_consent_modals: bool = False) -> SavedHeatmap:
        return SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=target_widths or [1024],
            status=SavedHeatmap.Status.PROCESSING,
            block_consent_modals=block_consent_modals,
        )

    @parameterized.expand([("blocking_on", True), ("blocking_off", False)])
    @override_settings(**BROWSERLESS_SETTINGS, HEATMAP_BROWSERLESS_BLOCK_ADS=False)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_per_heatmap_consent_blocking_flows_into_body(
        self, _name: str, block_consent_modals: bool, mock_requests: MagicMock
    ) -> None:
        mock_requests.post.return_value = _make_response(_jpeg(b"1024"))

        heatmap = self._make_heatmap(block_consent_modals=block_consent_modals)
        generate_heatmap_screenshot(heatmap.id)

        body = mock_requests.post.call_args.kwargs["json"]
        if block_consent_modals:
            assert body["blockConsentModals"] is True
        else:
            assert "blockConsentModals" not in body

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_uses_rest_screenshot_api(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _make_response(_jpeg(b"1024"))

        heatmap = self._make_heatmap()
        generate_heatmap_screenshot(heatmap.id)

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
        assert snaps == {1024: _jpeg(b"1024")}

        # A mode-usage event is captured on success
        assert len(self.captured_events) == 1
        event = self.captured_events[0]
        assert event["event"] == "heatmap screenshot generated"
        assert event["properties"]["mode"] == "browserless"
        assert event["properties"]["success"] is True
        assert event["properties"]["width_count"] == 1
        assert event["properties"]["duration_seconds"] is not None
        assert event["groups"]["project"] == str(self.team.id)

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_one_request_per_width(self, mock_requests: MagicMock) -> None:
        mock_requests.post.side_effect = [
            _make_response(_jpeg(b"320")),
            _make_response(_jpeg(b"768")),
            _make_response(_jpeg(b"1024")),
        ]

        heatmap = self._make_heatmap(target_widths=[320, 768, 1024])
        generate_heatmap_screenshot(heatmap.id)

        # One /screenshot request per width, each carrying its own viewport width
        assert mock_requests.post.call_count == 3
        bodies = [call.kwargs["json"] for call in mock_requests.post.call_args_list]
        assert [body["viewport"]["width"] for body in bodies] == [320, 768, 1024]
        # Narrow widths render as a touch/mobile viewport
        assert bodies[0]["viewport"]["isMobile"] is True
        assert bodies[2]["viewport"]["isMobile"] is False

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED
        # Each width's bytes land on the matching row (the width→image mapping must be preserved)
        snaps = {s.width: s.content for s in HeatmapSnapshot.objects.filter(heatmap=heatmap)}
        assert snaps == {320: _jpeg(b"320"), 768: _jpeg(b"768"), 1024: _jpeg(b"1024")}

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_failure_on_later_width_marks_failed_and_keeps_earlier_widths(self, mock_requests: MagicMock) -> None:
        # First width succeeds, second width's request fails
        mock_requests.post.side_effect = [_make_response(_jpeg(b"320")), Exception("boom on second width")]

        heatmap = self._make_heatmap(target_widths=[320, 768])

        with self.assertRaises(BrowserlessError):
            generate_heatmap_screenshot(heatmap.id)

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        # Each width persists as it renders, so the earlier success is kept and the failed width is
        # simply absent (bounded worker memory > all-or-nothing persistence).
        snaps = {s.width: s.content for s in HeatmapSnapshot.objects.filter(heatmap=heatmap)}
        assert snaps == {320: _jpeg(b"320")}
        assert self.captured_events[-1]["properties"]["mode"] == "browserless"
        assert self.captured_events[-1]["properties"]["success"] is False
        assert self.captured_events[-1]["properties"]["error_type"] == "BrowserlessTransientError"
        assert self.captured_events[-1]["properties"]["failure_type"] == "browserless_timeout"

    @override_settings(HEATMAP_BROWSERLESS_URL="")
    def test_unconfigured_url_marks_failed_permanently(self) -> None:
        heatmap = self._make_heatmap()

        with self.assertRaises(BrowserlessPermanentError):
            generate_heatmap_screenshot(heatmap.id)

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        assert "not configured" in (heatmap.exception or "")

    def test_resolve_widths_caps_render_fan_out(self) -> None:
        # A heatmap created before the serializer cap (or via regenerate) can carry an unbounded
        # widths list; the worker must still bound the per-width render fan-out.
        heatmap = self._make_heatmap(
            target_widths=list(range(100, 100 + 5 * (MAX_TARGET_WIDTHS + 50), 5)),  # well over the cap
        )
        widths = _resolve_widths(heatmap)
        assert len(widths) == MAX_TARGET_WIDTHS


# Pure-function tests for the Browserless REST helper — no DB, so they run on SimpleTestCase.
class TestBrowserlessScreenshotRequest(SimpleTestCase):
    @parameterized.expand([("desktop", 1024, False), ("mobile", 320, True)])
    @override_settings(
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
        HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000,
        HEATMAP_BROWSERLESS_BLOCK_ADS=False,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_posts_full_page_body_with_viewport_width(
        self, _name: str, width: int, is_mobile: bool, mock_requests: MagicMock
    ) -> None:
        mock_requests.post.return_value = _make_response(_jpeg(b"img"))

        content = _browserless_screenshot(
            "https://host/screenshot?token=t", "https://example.com", width, block_consent_modals=True
        )

        assert content == _jpeg(b"img")
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
        mock_requests.post.return_value = _make_response()
        _browserless_screenshot(
            "https://host/screenshot?token=t", "https://example.com", 1024, block_consent_modals=False
        )
        assert mock_requests.post.call_args.kwargs["json"]["blockAds"] is True

    @override_settings(
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
        HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000,
        HEATMAP_BROWSERLESS_BLOCK_ADS=False,
    )
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_cloud_only_fields_omitted_when_disabled(self, mock_requests: MagicMock) -> None:
        # The self-hosted OSS browserless image rejects bodies carrying these cloud-only fields,
        # so disabling them must omit the keys entirely rather than send false.
        mock_requests.post.return_value = _make_response()
        _browserless_screenshot(
            "https://host/screenshot?token=t", "https://example.com", 1024, block_consent_modals=False
        )
        body = mock_requests.post.call_args.kwargs["json"]
        assert "blockAds" not in body
        assert "blockConsentModals" not in body

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

        with self.assertRaises(BrowserlessError) as ctx:
            _browserless_screenshot(endpoint, "https://example.com", 1024, block_consent_modals=False)

        message = str(ctx.exception)
        # The token must never reach the (API-readable) persisted exception
        assert "secret-token" not in message
        assert "REDACTED" in message

    @parameterized.expand(
        [
            ("empty_body", b"", "image/jpeg"),
            ("non_image_content_type", b'{"error":"nope"}', "application/json"),
            ("non_jpeg_body", b"\x89PNG\r\n", "image/png"),
        ]
    )
    @override_settings(HEATMAP_BROWSERLESS_TIMEOUT_MS=180000, HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_rejects_invalid_200_body(
        self, _name: str, content: bytes, content_type: str, mock_requests: MagicMock
    ) -> None:
        # A 200 that isn't a real JPEG must not be stored and served as image/jpeg.
        mock_requests.post.return_value = _make_response(content, content_type=content_type)
        with self.assertRaises(BrowserlessError):
            _browserless_screenshot(
                "https://host/screenshot?token=t", "https://example.com", 1024, block_consent_modals=False
            )

    @override_settings(HEATMAP_BROWSERLESS_TIMEOUT_MS=180000, HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS=30000)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.HEATMAP_SCREENSHOT_MAX_BYTES", 8)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.requests")
    def test_rejects_oversized_body_as_permanent(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _make_response(_jpeg(b"way over the cap"))
        with self.assertRaises(BrowserlessPermanentError):
            _browserless_screenshot(
                "https://host/screenshot?token=t", "https://example.com", 1024, block_consent_modals=False
            )


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

    @parameterized.expand(
        [
            ("http", "http://browserless:3000", "http://browserless:3000/screenshot?"),
            ("ws", "ws://browserless:3000", "http://browserless:3000/screenshot?"),
            ("https", "https://host.example", "https://host.example/screenshot?"),
        ]
    )
    def test_build_screenshot_url_preserves_plain_http_scheme(self, _name: str, base: str, expected: str) -> None:
        # In-network Browserless (e.g. hobby's http://browserless:3000) serves plain http; only
        # secure or schemeless URLs are forced to https.
        with override_settings(
            HEATMAP_BROWSERLESS_URL=base, HEATMAP_BROWSERLESS_TOKEN="t", HEATMAP_BROWSERLESS_TIMEOUT_MS=180000
        ):
            url = _build_browserless_screenshot_url()
        assert url is not None
        assert url.startswith(expected)

    @override_settings(
        HEATMAP_BROWSERLESS_URL="wss://localhost:3000/chromium",
        HEATMAP_BROWSERLESS_TOKEN="t",
        HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
    )
    def test_build_screenshot_url_preserves_non_default_port(self) -> None:
        # Self-hosted / local Browserless runs on a non-443 port; dropping it would post to the wrong host.
        url = _build_browserless_screenshot_url()
        assert url is not None
        assert url.startswith("https://localhost:3000/screenshot?")

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


class TestClassifyFailure(SimpleTestCase):
    @parameterized.expand(
        [
            ("soft_time_limit", SoftTimeLimitExceeded(), "soft_time_limit"),
            ("not_configured", BrowserlessPermanentError("x", cause="not_configured"), "not_configured"),
            ("oversized", BrowserlessPermanentError("x", cause="oversized"), "validation_error"),
            ("empty_body", BrowserlessTransientError("x", cause="empty_body"), "validation_error"),
            ("non_image", BrowserlessTransientError("x", cause="non_image"), "validation_error"),
            ("non_jpeg", BrowserlessTransientError("x", cause="non_jpeg"), "validation_error"),
            ("request_exception", BrowserlessTransientError("x", cause="request_exception"), "browserless_timeout"),
            ("http_408", BrowserlessTransientError("x", status_code=408, cause="http_status"), "browserless_timeout"),
            ("http_429", BrowserlessTransientError("x", status_code=429, cause="http_status"), "browserless_4xx"),
            ("http_404", BrowserlessPermanentError("x", status_code=404, cause="http_status"), "browserless_4xx"),
            ("http_503", BrowserlessTransientError("x", status_code=503, cause="http_status"), "browserless_5xx"),
            ("unknown", ValueError("x"), "unknown"),
        ]
    )
    def test_classify_failure(self, _name: str, exc: BaseException, expected: str) -> None:
        assert _classify_failure(exc) == expected


class TestReportStuckHeatmapScreenshots(APIBaseTest):
    def _make(
        self, *, status: str, type_: str = SavedHeatmap.Type.SCREENSHOT, age_seconds: int | None = None
    ) -> SavedHeatmap:
        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[1024],
            type=type_,
            status=status,
        )
        if age_seconds is not None:
            SavedHeatmap.objects.filter(id=heatmap.id).update(
                updated_at=timezone.now() - timedelta(seconds=age_seconds)
            )
        return heatmap

    def test_reports_only_old_processing_screenshots_without_mutating_them(self) -> None:
        old = HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS + 60
        stuck = self._make(status=SavedHeatmap.Status.PROCESSING, age_seconds=old)
        fresh = self._make(status=SavedHeatmap.Status.PROCESSING, age_seconds=30)
        completed = self._make(status=SavedHeatmap.Status.COMPLETED, age_seconds=old)
        iframe = self._make(status=SavedHeatmap.Status.PROCESSING, type_=SavedHeatmap.Type.IFRAME, age_seconds=old)

        count = report_stuck_heatmap_screenshots()

        assert count == 1
        for heatmap in (stuck, fresh, completed, iframe):
            heatmap.refresh_from_db()
        assert stuck.status == SavedHeatmap.Status.PROCESSING
        assert fresh.status == SavedHeatmap.Status.PROCESSING
        assert completed.status == SavedHeatmap.Status.COMPLETED
        assert iframe.status == SavedHeatmap.Status.PROCESSING

    def test_gauge_reflects_count_and_resets_when_clear(self) -> None:
        def _gauge() -> float:
            return REGISTRY.get_sample_value("heatmap_screenshot_stuck_processing") or 0.0

        old = HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS + 60
        self._make(status=SavedHeatmap.Status.PROCESSING, age_seconds=old)
        self._make(status=SavedHeatmap.Status.PROCESSING, age_seconds=old)

        assert report_stuck_heatmap_screenshots() == 2
        assert _gauge() == 2

        SavedHeatmap.objects.update(status=SavedHeatmap.Status.COMPLETED)

        assert report_stuck_heatmap_screenshots() == 0
        assert _gauge() == 0

    def test_logs_full_count_but_caps_the_sample(self) -> None:
        old = HEATMAP_SCREENSHOT_STUCK_THRESHOLD_SECONDS + 60
        over_cap = HEATMAP_SCREENSHOT_STUCK_SAMPLE_SIZE + 5
        for _ in range(over_cap):
            self._make(status=SavedHeatmap.Status.PROCESSING, age_seconds=old)

        with patch("products.web_analytics.backend.tasks.heatmap_screenshot.logger") as mock_logger:
            count = report_stuck_heatmap_screenshots()

        assert count == over_cap
        _args, kwargs = mock_logger.warning.call_args
        assert kwargs["stuck_count"] == over_cap
        assert len(kwargs["sample"]) == HEATMAP_SCREENSHOT_STUCK_SAMPLE_SIZE
