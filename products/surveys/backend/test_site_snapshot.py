import json
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.event_definitions.backend.models import PropertyDefinition
from products.exports.backend.facade.api import EXPORT_WORKFLOW_TIMEOUT
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
EARLY_START = "https://example.com/early-start"
TWO_TABS = "https://example.com/two-tabs"
SESSION_OFFSET_SECONDS = 10


@time_machine.travel("2026-11-06 12:00:00", tick=False)
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
        self._view("giant", "https://example.com/giant", hours_ago=2, viewport=(1440, 100_000))
        self._view("early", EARLY_START, hours_ago=60, pageview_offset=timedelta(seconds=-30))
        self._view("bounce", "https://example.com/bounce", hours_ago=72, left_after=timedelta(seconds=1))
        self._view("two-tabs", TWO_TABS, hours_ago=84, left_after=timedelta(seconds=1), next_page_window="other-tab")
        flush_persons_and_events()

    def _view(
        self,
        session_id: str,
        url: str,
        *,
        hours_ago: int,
        viewport: tuple[int, int] = (1440, 900),
        has_replay: bool = True,
        pageview_offset: timedelta = timedelta(seconds=SESSION_OFFSET_SECONDS),
        left_after: timedelta | None = None,
        next_page_window: str = "first-tab",
    ) -> None:
        replay_start = timezone.now() - timedelta(hours=hours_ago)
        _create_event(
            team=self.team,
            distinct_id=session_id,
            event="$pageview",
            timestamp=replay_start + pageview_offset,
            properties={
                "$session_id": session_id,
                "$window_id": "first-tab",
                "$current_url": url,
                "$viewport_width": viewport[0],
                "$viewport_height": viewport[1],
            },
        )
        if left_after is not None:
            _create_event(
                team=self.team,
                distinct_id=session_id,
                event="$pageview",
                timestamp=replay_start + pageview_offset + left_after,
                properties={
                    "$session_id": session_id,
                    "$window_id": next_page_window,
                    "$current_url": "https://example.com/next-page",
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
            ("viewport_too_tall_to_render", {"url": "giant"}, None),
            ("pageview_just_before_the_recorder_starts", {"url": "early-start"}, EARLY_START),
            ("visitor_left_before_the_page_painted", {"url": "bounce"}, None),
            ("another_tab_navigated_meanwhile", {"url": "two-tabs"}, TWO_TABS),
            ("regex_clickhouse_cannot_compile", {"url": "^(?!.*admin).*", "urlMatchType": "regex"}, None),
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
        assert "page_url" not in asset.export_context
        assert str(survey.id) not in json.dumps(asset.export_context)
        assert (first.status, first.exported_asset_id, first.page_url, first.viewport_width) == (
            SnapshotStatus.RENDERING,
            asset.id,
            DOCS,
            1440,
        )

        asset.content = b"png"
        asset.save()
        second = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert (second.status, second.exported_asset_id, second.page_url) == (SnapshotStatus.READY, asset.id, DOCS)
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

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_renders_again_from_another_recording_when_the_cached_one_was_deleted(
        self, _async_connect: AsyncMock
    ) -> None:
        survey = self._survey(None)
        get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)
        replay_start = timezone.now() - timedelta(hours=24)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="docs",
            distinct_id="docs",
            first_timestamp=replay_start,
            last_timestamp=replay_start + timedelta(minutes=1),
            ensure_analytics_event_in_session=False,
            is_deleted=True,
        )

        snapshot = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert (snapshot.status, snapshot.page_url) == (SnapshotStatus.RENDERING, PRICING)
        assert ExportedAsset.objects.count() == 2

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_ignores_an_export_a_user_created_with_the_snapshot_key(self, _async_connect: AsyncMock) -> None:
        survey = self._survey(None)
        get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)
        ExportedAsset.objects.update(is_system=False, content=b"planted")

        snapshot = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert snapshot.status == SnapshotStatus.RENDERING
        assert ExportedAsset.objects.count() == 2

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_renders_again_when_a_render_was_abandoned(self, _async_connect: AsyncMock) -> None:
        survey = self._survey(None)
        get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)
        ExportedAsset.objects.update(created_at=timezone.now() - EXPORT_WORKFLOW_TIMEOUT - timedelta(minutes=1))

        snapshot = get_site_snapshot(self.team, survey, SnapshotDevice.DESKTOP, self.user)

        assert snapshot.status == SnapshotStatus.RENDERING
        assert ExportedAsset.objects.count() == 2

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_a_viewer_grant_on_the_recording_is_enough(self, _async_connect: AsyncMock) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        recording = SessionRecording.objects.create(team=self.team, session_id="docs", distinct_id="docs")
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="session_recording", access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=str(recording.id),
            access_level="viewer",
            organization_member=membership,
        )

        snapshot = get_site_snapshot(self.team, self._survey({"url": "docs"}), SnapshotDevice.DESKTOP, self.user)

        assert (snapshot.status, snapshot.page_url) == (SnapshotStatus.RENDERING, DOCS)

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_is_unavailable_when_page_urls_are_restricted(self, _async_connect: AsyncMock) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        current_url = PropertyDefinition.objects.create(
            team=self.team, name="$current_url", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=current_url, access_level=PropertyAccessLevel.NONE.value
        )

        snapshot = get_site_snapshot(self.team, self._survey(None), SnapshotDevice.DESKTOP, self.user)

        assert snapshot == SiteSnapshot(status=SnapshotStatus.UNAVAILABLE)
        assert not ExportedAsset.objects.exists()

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
