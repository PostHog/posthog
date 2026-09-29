from datetime import timedelta

from django.utils import timezone

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestObservationThumbnail(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="sess-1",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
        )

    def _url(self) -> str:
        return f"{self.observations_url(self.scanner.id)}{self.observation.id}/thumbnail/"

    def _add_thumbnail(self, *, rendered: bool) -> ExportedAsset:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id)},
            content_location=f"replay-vision/media/team-{self.team.id}/{self.observation.id}/x.png"
            if rendered
            else None,
            is_system=True,
        )
        ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=self.observation,
            asset=asset,
            kind=ReplayObservationMedia.Kind.THUMBNAIL,
            position=0,
            video_start_ms=1000,
        )
        return asset

    def test_it_serves_the_image(self) -> None:
        self._add_thumbnail(rendered=True)

        response = self.client.get(self._url())

        assert response.status_code in (200, 302)
        # The response redirects to a signed, expiring URL, so a cached one would outlive its target.
        assert response.headers["Cache-Control"] == "no-store"

    def test_the_export_endpoint_will_not_serve_an_observations_media(self) -> None:
        # That endpoint authorizes a recording export by the recording alone, which is weaker than the
        # scanner and experiment checks this observation's own endpoint applies.
        asset = self._add_thumbnail(rendered=True)

        response = self.client.get(f"/api/projects/{self.team.id}/exports/{asset.id}/content")

        assert response.status_code == 404

    def test_an_unfinished_render_is_not_found(self) -> None:
        self._add_thumbnail(rendered=False)

        assert self.client.get(self._url()).status_code == 404

    def test_an_expired_frame_is_not_served(self) -> None:
        # The sweep deletes the object some time after the row expires, and until then the join would
        # still hand it out.
        asset = self._add_thumbnail(rendered=True)
        ExportedAsset.objects_including_ttl_deleted.filter(pk=asset.pk).update(
            expires_after=timezone.now() - timedelta(seconds=1)
        )

        assert self.client.get(self._url()).status_code == 404
