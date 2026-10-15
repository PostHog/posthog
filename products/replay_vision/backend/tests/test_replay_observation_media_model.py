import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.utils import uuid7

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType


class TestReplayObservationMediaTenancy(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=f"s-{uuid7()}",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        self.other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")

    def _asset(self, team: Team) -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=team, export_format=ExportedAsset.ExportFormat.PNG, export_context={}, is_system=True
        )

    def test_the_team_comes_from_the_observation(self) -> None:
        media = ReplayObservationMedia.objects.for_team(self.team.id).create(
            observation=self.observation,
            asset=self._asset(self.team),
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=1000,
        )

        assert media.team_id == self.observation.team_id

    def test_moving_an_existing_row_onto_another_teams_asset_is_refused(self) -> None:
        # The render's update_or_create repoints an existing row at a freshly created asset, so the
        # invariant has to hold on the update too, not only the insert.
        media = ReplayObservationMedia.objects.for_team(self.team.id).create(
            observation=self.observation,
            asset=self._asset(self.team),
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=1000,
        )
        media.asset = self._asset(self.other_team)

        with pytest.raises(ValueError):
            media.save(update_fields=["asset"])

    def test_an_asset_from_another_team_is_refused(self) -> None:
        # Nothing here comes from a request, so this is a guard against our own bug filing a frame under
        # the wrong tenant.
        with pytest.raises(ValueError):
            ReplayObservationMedia.objects.for_team(self.team.id).create(
                observation=self.observation,
                asset=self._asset(self.other_team),
                kind=ReplayObservationMedia.Kind.THUMBNAIL,
                position=0,
                video_start_ms=1000,
            )
