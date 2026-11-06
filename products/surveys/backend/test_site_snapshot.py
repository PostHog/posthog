from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.access_control.backend.models.access_control import AccessControl
from products.exports.backend.models.exported_asset import ExportedAsset
from products.surveys.backend.models import Survey
from products.surveys.backend.site_snapshot import (
    PAINT_DELAY_SECONDS,
    SiteSnapshot,
    SnapshotDevice,
    SnapshotStatus,
    find_snapshot_moment,
    get_site_snapshot,
)

DOCS = "https://example.com/docs/intro"
PRICING = "https://example.com/pricing"
MOBILE_HOME = "https://m.example.org/home"
SESSION_OFFSET_SECONDS = 10


class TestSiteSnapshot(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.session_recording_opt_in = True
        self.team.save()
        self._view("legacy", "https://example.com/legacy", hours_ago=24 * 8)
        self._view("pricing", PRICING, hours_ago=48)
        self._view("docs", DOCS, hours_ago=24)
        self._view("mobile", MOBILE_HOME, hours_ago=12, viewport=(390, 844))
        self._view("tablet", "https://example.com/tablet", hours_ago=6, viewport=(900, 1200))
        self._view("no-replay", "https://example.com/no-replay", hours_ago=1, has_replay=False)
        flush_persons_and_events()

    def _view(
        self,
        session_id: str,
        url: str,
        *,
        hours_ago: int,
        viewport: tuple[int, int] = (1440, 900),
        has_replay: bool = True,
    ) -> None:
        replay_start = timezone.now() - timedelta(hours=hours_ago)
        _create_event(
            team=self.team,
            distinct_id=session_id,
            event="$pageview",
            timestamp=replay_start + timedelta(seconds=SESSION_OFFSET_SECONDS),
            properties={
                "$session_id": session_id,
                "$current_url": url,
                "$viewport_width": viewport[0],
                "$viewport_height": viewport[1],
            },
        )
        if has_replay:
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=session_id,
                first_timestamp=replay_start,
                last_timestamp=replay_start + timedelta(minutes=1),
                ensure_analytics_event_in_session=False,
            )

    def _survey(self, conditions: dict[str, Any] | None) -> Survey:
        return Survey.objects.create(team=self.team, name="Draft", type="popover", conditions=conditions)

    @parameterized.expand(
        [
            ("regex", {"url": "/docs/.+", "urlMatchType": "regex"}, DOCS),
            ("not_regex", {"url": "docs", "urlMatchType": "not_regex"}, PRICING),
            ("exact", {"url": PRICING, "urlMatchType": "exact"}, PRICING),
            ("is_not", {"url": DOCS, "urlMatchType": "is_not"}, PRICING),
            ("icontains", {"url": "DOCS", "urlMatchType": "icontains"}, DOCS),
            ("not_icontains", {"url": "docs", "urlMatchType": "not_icontains"}, PRICING),
            ("missing_match_type_means_icontains", {"url": "DOCS"}, DOCS),
            ("missing_url_means_any_page", {}, DOCS),
            ("no_conditions_means_any_page", None, DOCS),
            ("older_than_the_window", {"url": "legacy"}, None),
            ("without_a_replay", {"url": "no-replay"}, None),
            ("on_another_device", {"url": "tablet"}, None),
        ]
    )
    def test_picks_the_newest_matching_page_with_a_replay(
        self, _name: str, conditions: dict[str, Any] | None, expected_url: str | None
    ) -> None:
        moment = find_snapshot_moment(self.team, self._survey(conditions), SnapshotDevice.DESKTOP)

        assert (moment.page_url if moment else None) == expected_url

    @parameterized.expand(
        [
            (SnapshotDevice.DESKTOP, "docs", DOCS),
            (SnapshotDevice.MOBILE, "mobile", MOBILE_HOME),
        ]
    )
    def test_filters_by_viewport_and_offsets_into_the_replay(
        self, device: SnapshotDevice, expected_session: str, expected_url: str
    ) -> None:
        moment = find_snapshot_moment(self.team, self._survey(None), device)

        assert moment is not None
        assert (moment.session_id, moment.page_url) == (expected_session, expected_url)
        assert moment.offset_seconds == SESSION_OFFSET_SECONDS + PAINT_DELAY_SECONDS

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_reuses_the_cached_snapshot(self, _async_connect: AsyncMock) -> None:
        survey = self._survey(None)

        first = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)
        asset = ExportedAsset.objects.get()
        assert asset.export_context is not None
        assert (
            asset.export_context["session_recording_id"],
            asset.export_context["width"],
            asset.export_context["height"],
        ) == ("docs", 1440, 900)
        assert (first.status, first.exported_asset_id, first.page_url) == (SnapshotStatus.RENDERING, asset.id, DOCS)

        asset.content = b"png"
        asset.save()
        second = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert (second.status, second.exported_asset_id) == (SnapshotStatus.READY, asset.id)
        assert ExportedAsset.objects.count() == 1

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_a_changed_url_condition_renders_a_new_snapshot(self, _async_connect: AsyncMock) -> None:
        survey = self._survey({"url": "docs"})
        get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        survey.conditions = {"url": "pricing"}
        snapshot = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert (snapshot.status, snapshot.page_url) == (SnapshotStatus.RENDERING, PRICING)
        assert ExportedAsset.objects.count() == 2

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_a_failed_render_is_unavailable(self, _async_connect: AsyncMock) -> None:
        survey = self._survey(None)
        get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)
        ExportedAsset.objects.update(exception="Render failed", exception_type="TimeoutError")

        snapshot = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert snapshot == SiteSnapshot(status=SnapshotStatus.UNAVAILABLE)
        assert ExportedAsset.objects.count() == 1

    @parameterized.expand(
        [
            ("replay_is_off", False, "viewer"),
            ("user_cannot_view_recordings", True, "none"),
        ]
    )
    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_is_unavailable_without_replay_access(
        self, _name: str, replay_on: bool, recording_access: str, _async_connect: AsyncMock
    ) -> None:
        self.team.session_recording_opt_in = replay_on
        self.team.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(team=self.team, resource="session_recording", access_level=recording_access)

        snapshot = get_site_snapshot(self.team, self._survey(None), SnapshotDevice.DESKTOP, self.user)

        assert snapshot == SiteSnapshot(status=SnapshotStatus.UNAVAILABLE)
        assert not ExportedAsset.objects.exists()
