from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import (
    HEATMAP_BROWSERLESS_FLAG,
    _build_browserless_cdp_url,
    _redact_browserless_url,
    _use_browserless_for_screenshot,
    generate_heatmap_screenshot,
)

BROWSERLESS_SETTINGS = {
    "HEATMAP_BROWSERLESS_URL": "wss://production-sfo.browserless.io/chromium",
    "HEATMAP_BROWSERLESS_TOKEN": "secret-token",
    "HEATMAP_BROWSERLESS_TIMEOUT_MS": 180000,
    "HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS": 30000,
}


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

        # Ensure we cleaned up the browser
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

    @override_settings(**BROWSERLESS_SETTINGS)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot._use_browserless_for_screenshot", return_value=True)
    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.sync_playwright")
    def test_cloud_path_connects_over_cdp_and_skips_local_launch_and_route(
        self, mock_sync_playwright: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.connect_over_cdp.return_value = mock_browser
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

        # Connect over CDP, never launch a local browser
        mock_p.chromium.launch.assert_not_called()
        mock_p.chromium.connect_over_cdp.assert_called_once()
        cdp_url = mock_p.chromium.connect_over_cdp.call_args.args[0]
        assert "/chromium" in cdp_url
        assert "token=secret-token" in cdp_url
        assert "timeout=180000" in cdp_url
        assert mock_p.chromium.connect_over_cdp.call_args.kwargs["timeout"] == 30000

        # On the cloud path we must NOT install per-request interception (would round-trip the WAN)
        mock_page.route.assert_not_called()

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED

        # The mode-usage event reflects the browserless path
        assert self.captured_events[-1]["properties"]["mode"] == "browserless"
        assert self.captured_events[-1]["properties"]["success"] is True

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

        mock_p.chromium.connect_over_cdp.assert_not_called()
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

        def recording_get_or_create(*args: object, **kwargs: object) -> object:
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
    def test_connect_failure_does_not_leak_token(
        self, mock_sync_playwright: MagicMock, mock_use_browserless: MagicMock
    ) -> None:
        mock_p = MagicMock()
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        # Playwright echoes the full endpoint URL (incl. the token) into connect errors
        mock_p.chromium.connect_over_cdp.side_effect = RuntimeError(
            "connect ECONNREFUSED wss://production-sfo.browserless.io/chromium?token=secret-token&timeout=180000"
        )

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        with self.assertRaises(RuntimeError):
            generate_heatmap_screenshot(heatmap.id)

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        # The token must never reach the persisted (API-readable) exception column
        assert "secret-token" not in (heatmap.exception or "")
        assert "REDACTED" in (heatmap.exception or "")

        # Failure event records the browserless mode + a non-sensitive error type (no token leak)
        failure_event = self.captured_events[-1]
        assert failure_event["properties"]["mode"] == "browserless"
        assert failure_event["properties"]["success"] is False
        assert failure_event["properties"]["error_type"] == "RuntimeError"
        assert "secret-token" not in str(failure_event)

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
        mock_p.chromium.connect_over_cdp.assert_not_called()
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


# Pure-function tests for the Browserless URL helpers — no DB, so they run on SimpleTestCase.
class TestBrowserlessUrlHelpers(SimpleTestCase):
    @override_settings(HEATMAP_BROWSERLESS_URL="")
    def test_build_cdp_url_returns_none_when_unset(self) -> None:
        assert _build_browserless_cdp_url() is None

    @parameterized.expand(
        [
            ("both_off", False, False, [], ["blockAds", "blockConsentModals"]),
            ("ads_on", True, False, ["blockAds=true"], ["blockConsentModals"]),
            ("both_on", True, True, ["blockAds=true", "blockConsentModals=true"], []),
        ]
    )
    def test_build_cdp_url_block_params(
        self, _name: str, ads: bool, consent: bool, present: list[str], absent: list[str]
    ) -> None:
        with override_settings(
            HEATMAP_BROWSERLESS_URL="wss://host/chromium?foo=bar",
            HEATMAP_BROWSERLESS_TOKEN="t",
            HEATMAP_BROWSERLESS_TIMEOUT_MS=180000,
            HEATMAP_BROWSERLESS_BLOCK_ADS=ads,
            HEATMAP_BROWSERLESS_BLOCK_CONSENT_MODALS=consent,
        ):
            url = _build_browserless_cdp_url()

        assert url is not None
        # Pre-existing query is preserved, our params are appended
        assert "foo=bar" in url
        assert "token=t" in url
        assert "timeout=180000" in url
        for fragment in present:
            assert fragment in url
        for fragment in absent:
            assert fragment not in url

    def test_redact_browserless_url_strips_token_and_userinfo(self) -> None:
        redacted = _redact_browserless_url("wss://user:pass@host:3000/chromium?token=supersecret&timeout=1000")
        assert "supersecret" not in redacted
        assert "user" not in redacted
        assert "pass" not in redacted
        assert "token=REDACTED" in redacted
        # Non-sensitive params survive
        assert "timeout=1000" in redacted
