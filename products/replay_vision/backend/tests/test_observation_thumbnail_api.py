from datetime import timedelta

from unittest.mock import patch

from django.http import HttpResponse
from django.utils import timezone

from parameterized import parameterized

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

    def _png(self, *, rendered: bool, name: str = "x") -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"observation_id": str(self.observation.id)},
            content_location=f"replay-vision/media/team-{self.team.id}/{self.observation.id}/{name}.png"
            if rendered
            else None,
            is_system=True,
        )

    def _add_thumbnail(
        self,
        *,
        rendered: bool,
        kind: ReplayObservationMedia.Kind = ReplayObservationMedia.Kind.THUMBNAIL,
        position: int = 0,
        small_asset: ExportedAsset | None = None,
    ) -> ExportedAsset:
        asset = self._png(rendered=rendered)
        ReplayObservationMedia.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            observation=self.observation,
            asset=asset,
            small_asset=small_asset,
            kind=kind,
            position=position,
            video_start_ms=1000,
        )
        return asset

    def test_it_serves_the_image(self) -> None:
        self._add_thumbnail(rendered=True)

        response = self.client.get(self._url())

        assert response.status_code in (200, 302)
        # The redirect target is signed for an hour, so a cache longer than that would outlive it.
        assert response.headers["Cache-Control"] == "private, max-age=600"

    @parameterized.expand(
        [
            ("small_requested", "small", "rendered", "small"),
            ("large_requested", "large", "rendered", "large"),
            ("no_size_means_large", None, "rendered", "large"),
            ("small_missing_falls_back", "small", None, "large"),
            ("small_unfinished_falls_back", "small", "unrendered", "large"),
            ("small_expired_falls_back", "small", "expired", "large"),
        ]
    )
    def test_the_size_picks_which_copy_is_served(
        self, _name: str, size: str | None, small_state: str | None, expected: str
    ) -> None:
        small = None if small_state is None else self._png(rendered=small_state != "unrendered", name="small")
        if small_state == "expired":
            assert small is not None
            ExportedAsset.objects_including_ttl_deleted.filter(pk=small.pk).update(
                expires_after=timezone.now() - timedelta(seconds=1)
            )
        large = self._add_thumbnail(rendered=True, small_asset=small)

        with patch(
            "products.replay_vision.backend.api.observations.get_export_asset_content_response",
            return_value=HttpResponse(),
        ) as serve:
            response = self.client.get(self._url(), {} if size is None else {"size": size})

        assert response.status_code == 200
        expected_asset = small if expected == "small" else large
        assert expected_asset is not None
        assert serve.call_args.kwargs["asset"].pk == expected_asset.pk

    def test_a_chapter_frame_is_served_only_for_its_chapter(self) -> None:
        self._add_thumbnail(rendered=True, kind=ReplayObservationMedia.Kind.CHAPTER, position=1)

        assert self.client.get(self._url(), {"chapter": 1}).status_code in (200, 302)
        assert self.client.get(self._url(), {"chapter": 2}).status_code == 404
        assert self.client.get(self._url()).status_code == 404

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
