from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Barrier
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import close_old_connections, connections
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from PIL import Image

from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorageError

from products.web_analytics.backend.heatmap_history import (
    CaptureCooldown,
    CaptureDispatchError,
    HeatmapHistoryService,
    capture_day,
    history_due_at,
    history_width,
)
from products.web_analytics.backend.heatmap_history_storage import image_key
from products.web_analytics.backend.models import HeatmapCaptureRequest, HeatmapScreenshotHistory, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import BrowserlessPermanentError

TASK_MODULE = "products.web_analytics.backend.heatmap_history"
RENDER_MODULE = "products.web_analytics.backend.tasks.heatmap_screenshot"
STORAGE_MODULE = "products.web_analytics.backend.heatmap_history_storage"


def jpeg(width: int = 1024) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, 100), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


class TestHistoryDates(SimpleTestCase):
    def test_latest_due_slot_leaves_time_before_midnight(self) -> None:
        day = capture_day(datetime(2024, 3, 10, 12, tzinfo=UTC), "America/New_York")
        due = history_due_at(UUID("00000000-0000-0000-0000-0000000000c2"), day)
        assert day.start < due < day.end - timedelta(minutes=30)

    @parameterized.expand(
        [
            ("spring", "2024-03-10T12:00:00+00:00", 23, "2024-03-10"),
            ("fall", "2024-11-03T12:00:00+00:00", 25, "2024-11-03"),
            ("midnight", "2024-05-02T02:00:00+00:00", 24, "2024-05-01"),
        ]
    )
    def test_project_day(self, _name: str, instant: str, hours: int, captured_on: str) -> None:
        day = capture_day(datetime.fromisoformat(instant), "America/New_York")
        assert day.end - day.start == timedelta(hours=hours)
        assert day.captured_on.isoformat() == captured_on

    @parameterized.expand([([320, 1024, 1920], 1024), ([320, 768, 1440], 768), ([800, 1248], 800), ([], 1024)])
    def test_history_width(self, widths: list[int], expected: int) -> None:
        assert history_width(SavedHeatmap(target_widths=widths)) == expected


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestHeatmapHistory(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            target_widths=[1024],
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
            last_viewed_at=timezone.now(),
            next_history_capture_at=timezone.now(),
        )
        self.blobs: dict[str, bytes] = {}
        self.storage = MagicMock()
        self.storage.write.side_effect = lambda key, content, **kwargs: self.blobs.update({key: content})
        self.storage.read_bytes.side_effect = lambda key, **kwargs: self.blobs.get(key)
        self.storage.delete_objects.side_effect = self.delete_blobs
        for name, replacement in [
            (f"{STORAGE_MODULE}.object_storage", self.storage),
            (f"{TASK_MODULE}.history_enabled", lambda team: True),
        ]:
            patcher = patch(name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def enqueue(self, trigger: str = "manual") -> HeatmapCaptureRequest:
        with patch.object(HeatmapHistoryService, "dispatch"), self.captureOnCommitCallbacks(execute=True):
            request = HeatmapHistoryService.enqueue(team_id=self.team.id, heatmap_id=self.heatmap.id, trigger=trigger)
        assert request is not None
        return request

    def delete_blobs(self, keys: list[str], **kwargs: object) -> list[str]:
        for key in keys:
            self.blobs.pop(key, None)
        return []

    def images(self, request: HeatmapCaptureRequest) -> set[str]:
        return {key for key in self.blobs if f"/{request.id}/" in key}

    def execute_capture(self, request: HeatmapCaptureRequest, error: Exception | None = None) -> None:
        with (
            patch.object(HeatmapHistoryService, "render", return_value=jpeg(request.width), side_effect=error),
            self.captureOnCommitCallbacks(execute=True),
        ):
            claimed = HeatmapHistoryService.claim(team_id=self.team.id, request_id=request.id)
            if claimed is not None:
                outcome = HeatmapHistoryService.render_and_store(claimed, final_attempt=True)
                if outcome.failure_cause is None:
                    HeatmapHistoryService.publish(claimed, outcome.has_thumbnail)
                else:
                    HeatmapHistoryService.fail(claimed, outcome.failure_cause, outcome.page_status)
        request.refresh_from_db()

    def history(self) -> HeatmapScreenshotHistory:
        return HeatmapScreenshotHistory.objects.for_team(self.team.id).get(heatmap=self.heatmap)

    def allow_recapture(self) -> None:
        HeatmapCaptureRequest.objects.for_team(self.team.id).filter(heatmap=self.heatmap).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )

    def test_capture_claims_once_and_writes_both_images(self) -> None:
        request = self.enqueue()
        self.execute_capture(request)
        assert request.state == "succeeded"
        assert self.history().revision == request.id
        assert self.history().has_thumbnail
        assert {key.rsplit("/", 1)[1] for key in self.images(request)} == {"full.jpg", "thumbnail.jpg"}
        self.storage.write.reset_mock()
        self.execute_capture(request)
        self.storage.write.assert_not_called()

    def replace_with_manual_capture(self) -> None:
        self.execute_capture(self.enqueue())

    def toggle_render_setting_and_back(self) -> None:
        for value in (True, False):
            self.heatmap.block_consent_modals = value
            self.heatmap.save(update_fields=["block_consent_modals"])

    @parameterized.expand(
        [
            ("replaced_by_manual_capture", "replace_with_manual_capture", True),
            ("settings_changed_and_back", "toggle_render_setting_and_back", True),
            ("flag_disabled", None, False),
        ]
    )
    def test_late_publish_is_fenced(self, _name: str, change: str | None, enabled: bool) -> None:
        request = self.enqueue("scheduled")
        claimed = HeatmapHistoryService.claim(team_id=self.team.id, request_id=request.id)
        assert claimed is not None
        if change:
            getattr(self, change)()
        with patch(f"{TASK_MODULE}.history_enabled", return_value=enabled):
            HeatmapHistoryService.publish(claimed, True)
        assert self.history().revision != claimed.id

    def test_failed_replacement_preserves_good_image(self) -> None:
        good = self.enqueue()
        self.execute_capture(good)
        self.allow_recapture()
        bad = self.enqueue()
        self.execute_capture(bad, BrowserlessPermanentError("Failed", cause="invalid_image"))
        assert bad.state == "failed"
        history = self.history()
        assert history.revision == good.id
        assert history.status == "ok"
        assert history.has_content
        assert history.latest_request == bad
        assert self.images(good)
        assert not self.images(bad)

    def test_successful_replacement_deletes_old_images(self) -> None:
        old = self.enqueue()
        self.execute_capture(old)
        self.allow_recapture()
        new = self.enqueue()
        self.execute_capture(new)
        assert self.history().revision == new.id
        assert not self.images(old)
        assert self.images(new)

    def test_dispatch_failure_is_retryable_and_reported(self) -> None:
        with (
            self.assertRaises(CaptureDispatchError),
            patch(f"{TASK_MODULE}.async_connect", side_effect=RuntimeError("unavailable")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            HeatmapHistoryService.enqueue(team_id=self.team.id, heatmap_id=self.heatmap.id, trigger="manual")
        latest = self.history().latest_request
        assert latest is not None
        assert latest.failure_cause == "dispatch_failed"
        assert self.enqueue().state == "queued"

    @parameterized.expand(
        [
            ("url", "https://example.com/new"),
            ("data_url", "https://example.com/data"),
            ("deleted", True),
            ("hard_delete", None),
        ]
    )
    def test_configuration_reset_cancels_render_and_deletes_images(self, field: str, value: str | bool | None) -> None:
        request = self.enqueue()
        claimed = HeatmapHistoryService.claim(team_id=self.team.id, request_id=request.id)
        assert claimed is not None
        self.blobs[image_key(self.team.id, request.id, "full")] = jpeg()
        with self.captureOnCommitCallbacks(execute=True):
            if field == "hard_delete":
                self.heatmap.delete()
            else:
                setattr(self.heatmap, field, value)
                self.heatmap.save(update_fields=[field])
        assert not self.images(request)
        with self.captureOnCommitCallbacks(execute=True):
            HeatmapHistoryService.publish(claimed, True)
        assert not HeatmapScreenshotHistory.objects.for_team(self.team.id).exists()

    def test_thumbnail_failure_uses_no_full_image_fallback(self) -> None:
        request = self.enqueue()
        with patch.object(HeatmapHistoryService, "thumbnail", return_value=None):
            self.execute_capture(request)
        history = self.history()
        assert history.has_content
        assert not history.has_thumbnail

    @parameterized.expand(
        [
            ("HEATMAP_HISTORY_TEAM_DAILY_CAP", True),
            ("HEATMAP_HISTORY_GLOBAL_DAILY_CAP", False),
            ("HEATMAP_HISTORY_TICK_CAP", False),
        ]
    )
    def test_scheduled_reservations_enforce_caps(self, setting: str, waits_for_tomorrow: bool) -> None:
        self.enqueue("scheduled")
        second = SavedHeatmap.objects.create(
            team=self.team, url="https://example.com/second", status="completed", next_history_capture_at=timezone.now()
        )
        with patch(f"{TASK_MODULE}.{setting}", 1):
            assert (
                HeatmapHistoryService.enqueue(team_id=self.team.id, heatmap_id=second.id, trigger="scheduled") is None
            )
        second.refresh_from_db()
        assert second.next_history_capture_at is not None
        assert (second.next_history_capture_at > timezone.now()) == waits_for_tomorrow

    @parameterized.expand(
        [
            ("valid", jpeg(1024), True),
            ("wrong_width", jpeg(768), False),
            ("truncated", jpeg()[:-2], False),
            ("not_a_jpeg", b"not-a-jpeg", False),
        ]
    )
    def test_render_validates_complete_jpeg_and_dimensions(self, _name: str, image: bytes, valid: bool) -> None:
        request = self.enqueue()
        with (
            patch(f"{TASK_MODULE}.is_url_allowed", return_value=(True, None)),
            patch(f"{RENDER_MODULE}._build_browserless_screenshot_url", return_value="https://browserless.example.com"),
            patch(f"{RENDER_MODULE}._browserless_screenshot", return_value=(image, 200)),
        ):
            if valid:
                assert HeatmapHistoryService.render(request) == image
            else:
                with self.assertRaises(BrowserlessPermanentError):
                    HeatmapHistoryService.render(request)

    def test_request_deadline_is_capped_at_project_midnight(self) -> None:
        instant = datetime(2024, 3, 11, 3, 50, tzinfo=UTC)
        self.team.timezone = "America/New_York"
        self.team.save(update_fields=["timezone"])
        with patch(f"{TASK_MODULE}.timezone.now", return_value=instant):
            request = self.enqueue()
        assert request.captured_on.isoformat() == "2024-03-10"
        assert request.deadline == datetime(2024, 3, 11, 4, tzinfo=UTC)

    def test_pending_manual_capture_does_not_skip_automatic_capture_after_failure(self) -> None:
        manual = self.enqueue()
        assert (
            HeatmapHistoryService.enqueue(team_id=self.team.id, heatmap_id=self.heatmap.id, trigger="scheduled") is None
        )
        self.heatmap.refresh_from_db()
        assert self.heatmap.next_history_capture_at is not None
        assert self.heatmap.next_history_capture_at <= timezone.now()
        self.execute_capture(manual, BrowserlessPermanentError("Failed", cause="invalid_image"))
        assert self.enqueue("scheduled").state == "queued"

    def test_transient_storage_failure_retries_until_the_final_attempt(self) -> None:
        claimed = HeatmapHistoryService.claim(team_id=self.team.id, request_id=self.enqueue().id)
        assert claimed is not None
        self.storage.write.side_effect = ObjectStorageError("unavailable")
        with patch.object(HeatmapHistoryService, "render", return_value=jpeg()):
            with self.assertRaises(ObjectStorageError):
                HeatmapHistoryService.render_and_store(claimed, final_attempt=False)
            outcome = HeatmapHistoryService.render_and_store(claimed, final_attempt=True)
        assert outcome.failure_cause == "storage_write_failed"
        HeatmapCaptureRequest.objects.for_team(self.team.id).filter(id=claimed.id).update(
            deadline=timezone.now() + timedelta(seconds=60)
        )
        claimed.refresh_from_db()
        with patch.object(HeatmapHistoryService, "render", return_value=jpeg()):
            outcome = HeatmapHistoryService.render_and_store(claimed, final_attempt=False)
        assert outcome.failure_cause == "storage_write_failed"


@pytest.mark.django_db(transaction=True)
@override_settings(OBJECT_STORAGE_ENABLED=True)
def test_concurrent_requests_and_duplicate_delivery_have_one_winner() -> None:
    organization = Organization.objects.create(name="Concurrency test")
    team = Team.objects.create(organization=organization)
    heatmap = SavedHeatmap.objects.create(team=team, url="https://example.com", target_widths=[1024])
    barrier = Barrier(2)

    def enqueue() -> HeatmapCaptureRequest | None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return HeatmapHistoryService.enqueue(team_id=team.id, heatmap_id=heatmap.id, trigger="manual")
        except CaptureCooldown:
            return None
        finally:
            connections["default"].close()

    with (
        patch(f"{TASK_MODULE}.history_enabled", return_value=True),
        patch.object(HeatmapHistoryService, "dispatch"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        requests = list(pool.map(lambda _: enqueue(), range(2)))
    winners = [request for request in requests if request is not None]
    assert len(winners) == 1
    request_id = winners[0].id
    barrier = Barrier(2)

    def claim() -> HeatmapCaptureRequest | None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return HeatmapHistoryService.claim(team_id=team.id, request_id=request_id)
        finally:
            connections["default"].close()

    with patch(f"{TASK_MODULE}.history_enabled", return_value=True), ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert len([claim for claim in claims if claim is not None]) == 1
