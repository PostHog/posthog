from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from PIL import Image
from playwright.sync_api import Error as PlaywrightError

from posthog.models import User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.models import AccessControl
from products.exports.backend.models.exported_asset import ExportedAsset
from products.web_analytics.backend.heatmap_analysis import PageState, RecordingAnalysis, ReplayClick, group_page_states
from products.web_analytics.backend.models import SavedHeatmap
from products.web_analytics.backend.models.heatmap_analysis import HeatmapAnalysis, HeatmapAnalysisRecording
from products.web_analytics.backend.tasks.heatmap_analysis import analyze_heatmap, render_recording


def recording(
    image: str = "IMG:0:0:100:50:promotion-a", *, width: int = 1440, visit: str = "window-1:visit-1"
) -> RecordingAnalysis:
    return RecordingAnalysis(
        states=[
            PageState(
                window_id=1,
                timestamp=1000,
                visit_id=visit,
                width=width,
                height=1200,
                signature=["BUTTON:1:2:3:4:", image],
                image="123",
                clicks=[ReplayClick(x=16, y=24, target="BUTTON:1:2:3:4:", timestamp=1001)],
            )
        ]
    )


class TestPageVariants(SimpleTestCase):
    def test_promotions_with_the_same_geometry_are_separate(self) -> None:
        variants = group_page_states({"a": recording(), "b": recording("IMG:0:0:100:50:promotion-b"), "c": recording()})
        assert len(variants) == 2
        assert variants[0].summary()["recordings"] == 2
        assert variants[0].summary()["clicks"] == [{"x": 16, "y": 24, "count": 2}]
        assert variants[1].summary()["clicks"] == [{"x": 16, "y": 24, "count": 1}]

    def test_viewports_and_repeated_states_do_not_inflate_visits(self) -> None:
        first = recording()
        first.states.append(first.states[0].model_copy(update={"timestamp": 2000, "clicks": []}))
        variants = group_page_states({"a": first, "b": recording(width=375)})
        assert len(variants) == 2
        assert all(variant.summary()["visits"] == 1 for variant in variants)

    def test_removed_sources_remove_their_clicks_and_background(self) -> None:
        first, second = recording(), recording()
        second.states[0].image = "456"
        variants = group_page_states({"a": first, "b": second})
        selected = variants[0].member_id(variants[0].members[0])
        remaining = group_page_states({"b": second})
        assert remaining[0].representative(selected).state.image == "456"
        assert remaining[0].summary(selected)["clicks"] == [{"x": 16, "y": 24, "count": 1}]
        assert remaining[0].summary(selected)["representative_replaced"] is True

    def test_persisted_membership_survives_loss_of_the_cluster_origin(self) -> None:
        first, second = recording(), recording()
        second.states[0].signature.extend([f"A:{i}" for i in range(50)])
        first.states[0].signature = [*second.states[0].signature, "A:extra"]
        variant = group_page_states({"a": first, "b": second})[0]
        assert len(variant.members) == 2
        second.states[0].variant_id = variant.id
        remaining = group_page_states({"b": second})
        assert remaining[0].id == variant.id
        newcomer = recording()
        newcomer.states[0].signature = [*second.states[0].signature, "A:other"]
        joined = group_page_states({"0": newcomer, "b": second})
        assert [(item.id, len(item.members)) for item in joined] == [(variant.id, 2)]

    def test_clicks_without_matching_target_geometry_are_excluded(self) -> None:
        source = recording()
        source.states[0].clicks.append(ReplayClick(x=48, y=56, target="removed-target", timestamp=1002))
        assert group_page_states({"a": source})[0].summary()["clicks"] == [{"x": 16, "y": 24, "count": 1}]


class TestHistoricalHeatmapAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.session_recording_opt_in = True
        self.team.save()
        self.heatmap = SavedHeatmap.objects.create(team=self.team, url="https://example.com/specials")
        self.endpoint = f"/api/projects/{self.team.id}/heatmap_analyses/"
        self.body = {
            "heatmap_id": str(self.heatmap.id),
            "date_from": (timezone.now() - timedelta(days=7)).isoformat(),
            "date_to": timezone.now().isoformat(),
            "viewport_width": 1440,
        }
        self.flag = patch(
            "products.web_analytics.backend.api.heatmap_analyses.heatmaps_flag_enabled", return_value=True
        )
        self.flag.start()
        self.addCleanup(self.flag.stop)

    @parameterized.expand([("heatmap", False), ("session_recording", False), ("heatmap", True)])
    def test_saved_analysis_requires_replay_and_parent_heatmap_access(self, resource: str, object_level: bool) -> None:
        analysis = HeatmapAnalysis.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            heatmap=self.heatmap,
            url=self.heatmap.url,
            date_from=timezone.now() - timedelta(days=1),
            date_to=timezone.now(),
            viewport_width=1440,
            status="completed",
        )
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "historical-viewer@example.com", "password")
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(self.heatmap.id) if object_level else None,
            access_level="none",
        )
        self.client.force_login(member)
        assert self.client.get(f"{self.endpoint}{analysis.id}/").status_code == 403

    @parameterized.expand([(False,), (True,)])
    def test_worker_persists_membership_but_discards_sources_deleted_during_render(
        self, deleted_during_render: bool
    ) -> None:
        analysis = HeatmapAnalysis.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            heatmap=self.heatmap,
            url=self.heatmap.url,
            date_from=timezone.now() - timedelta(days=1),
            date_to=timezone.now(),
            viewport_width=1440,
        )

        def metadata(source: SessionRecording) -> bool:
            source.expiry_time = timezone.now() + timedelta(days=1)
            return True

        def render(_analysis: HeatmapAnalysis, _source: SessionRecording, asset: ExportedAsset) -> RecordingAnalysis:
            if deleted_during_render:
                asset.expires_after = timezone.now() - timedelta(seconds=1)
                asset.save(update_fields=["expires_after"])
            return recording()

        with (
            self.settings(BROWSERLESS_CDP_URL="http://localhost:3000", OBJECT_STORAGE_ENABLED=False),
            patch(
                "products.web_analytics.backend.tasks.heatmap_analysis.SessionRecordingListFromQuery.run",
                return_value=SimpleNamespace(results=[{"session_id": "synthetic-session"}], has_more_recording=False),
            ),
            patch.object(SessionRecording, "load_metadata", metadata),
            patch("products.web_analytics.backend.tasks.heatmap_analysis.render_recording", side_effect=render),
        ):
            analyze_heatmap(self.team.id, str(analysis.id))
        analysis.refresh_from_db()
        sources = HeatmapAnalysisRecording.objects.for_team(self.team.id).filter(analysis=analysis)
        assert analysis.sampled_recordings == 1
        if deleted_during_render:
            assert analysis.status == "partial"
            assert analysis.excluded_recordings == 1
            assert not sources.exists()
        else:
            assert analysis.status == "completed", analysis.error
            source = sources.get()
            assert source.asset.content is not None
            payload = RecordingAnalysis.model_validate_json(bytes(source.asset.content))
            assert payload.states[0].variant_id in analysis.representatives

    @parameterized.expand([(False,), (True,)])
    def test_render_saves_background_after_playwright_exits_its_event_loop(self, browser_closed: bool) -> None:
        analysis = HeatmapAnalysis.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            heatmap=self.heatmap,
            url=self.heatmap.url,
            date_from=timezone.now() - timedelta(days=1),
            date_to=timezone.now(),
            viewport_width=1440,
        )
        source = SessionRecording(team=self.team, session_id="synthetic-session")
        source.expiry_time = timezone.now() + timedelta(days=1)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.JSON,
            source_authentication=ExportedAsset.SourceAuthentication.SESSION,
            export_context={"session_recording_id": source.session_id, "historical_heatmap": True},
        )
        playwright = MagicMock()
        if browser_closed:
            playwright.chromium.connect_over_cdp.return_value.close.side_effect = PlaywrightError("Browser closed")
        page = playwright.chromium.connect_over_cdp.return_value.new_context.return_value.new_page.return_value
        page.evaluate.side_effect = [None, recording().model_dump(), True, 0]
        page.locator.return_value.bounding_box.return_value = {"width": 1440, "height": 1200}
        tile = BytesIO()
        Image.new("RGB", (1440, 1200), "white").save(tile, format="PNG")
        page.locator.return_value.screenshot.return_value = tile.getvalue()

        @contextmanager
        def browser_context() -> Iterator[MagicMock]:
            with patch("django.utils.asyncio.get_running_loop", return_value=object()):
                yield playwright

        with (
            self.settings(BROWSERLESS_CDP_URL="http://localhost:3000", OBJECT_STORAGE_ENABLED=False),
            patch("products.web_analytics.backend.tasks.heatmap_analysis.sync_playwright", browser_context),
        ):
            result = render_recording(analysis, source, asset)
        background = ExportedAsset.objects.get(team=self.team, id=result.states[0].image)
        assert background.content is not None
        assert bytes(background.content).startswith(b"\x89PNG")
        assert background.expires_after == source.expiry_time

    @patch("products.web_analytics.backend.api.heatmap_analyses.analyze_heatmap.delay")
    def test_create_deduplicates_and_rejects_invalid_ranges(self, enqueue: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.endpoint, self.body)
        assert response.status_code == 202, response.json()
        enqueue.assert_called_once_with(self.team.id, response.json()["id"])
        repeated = self.client.post(self.endpoint, self.body)
        assert repeated.status_code == 202
        assert repeated.json()["id"] == response.json()["id"]
        invalid = self.client.post(self.endpoint, {**self.body, "date_to": self.body["date_from"]})
        assert invalid.status_code == 400
        HeatmapAnalysis.objects.for_team(self.team.id).filter(id=response.json()["id"]).update(
            updated_at=timezone.now() - timedelta(minutes=16)
        )
        stalled = self.client.get(f"{self.endpoint}{response.json()['id']}/")
        assert stalled.json()["analysis"]["status"] == "failed"
        assert self.client.post(self.endpoint, self.body).status_code == 202

    def test_replay_disabled_and_cross_team_heatmap_fail_closed(self) -> None:
        assert self.client.get(f"{self.endpoint}invalid-id/").status_code == 404
        other_team = self.create_team_with_organization(self.organization)
        other = SavedHeatmap.objects.create(team=other_team, url="https://example.com/other")
        assert self.client.post(self.endpoint, {**self.body, "heatmap_id": str(other.id)}).status_code == 404
        self.team.session_recording_opt_in = False
        self.team.save()
        assert self.client.post(self.endpoint, self.body).status_code == 404

    @patch(
        "products.web_analytics.backend.api.heatmap_analyses.SessionReplayEvents.batch_exists",
        return_value={"synthetic-session": True},
    )
    def test_expired_export_removes_background_and_clicks(self, _exists: MagicMock) -> None:
        analysis = HeatmapAnalysis.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            heatmap=self.heatmap,
            url=self.heatmap.url,
            date_from=timezone.now() - timedelta(days=7),
            date_to=timezone.now(),
            viewport_width=1440,
            status="completed",
            sampled_recordings=1,
        )
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format="application/json",
            content=recording().model_dump_json().encode(),
            export_context={"session_recording_id": "synthetic-session"},
            expires_after=timezone.now() + timedelta(days=1),
        )
        HeatmapAnalysisRecording.objects.for_team(self.team.id).create(
            team=self.team,
            analysis=analysis,
            session_id="synthetic-session",
            asset=asset,
        )
        response = self.client.get(f"{self.endpoint}{analysis.id}/")
        assert response.status_code == 200, response.json()
        assert len(response.json()["variants"]) == 1
        variant_id = response.json()["variants"][0]["id"]
        moment_id = response.json()["variants"][0]["alternatives"][0]["id"]
        selected = self.client.post(
            f"{self.endpoint}{analysis.id}/representative/", {"variant_id": variant_id, "moment_id": moment_id}
        )
        assert selected.status_code == 200, selected.json()
        analysis.refresh_from_db()
        assert analysis.representatives == {variant_id: moment_id}
        asset.expires_after = timezone.now() - timedelta(seconds=1)
        asset.save()
        response = self.client.get(f"{self.endpoint}{analysis.id}/")
        assert response.json()["variants"] == []
        assert response.json()["unavailable_recordings"] == 1
        assert response.json()["analysis"]["status"] == "unavailable"
        assert self.client.get(f"{self.endpoint}{analysis.id}/background/{variant_id}/").status_code == 404
