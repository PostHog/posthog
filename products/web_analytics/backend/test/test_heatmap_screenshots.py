from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Team

from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap


class TestHeatmapsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_generate_creates_saved_with_target_widths(self, mock_task):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {"url": "https://example.com", "widths": [768, 1024]},
        )
        self.assertEqual(resp.status_code, 201)
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertEqual(saved.url, "https://example.com")
        self.assertEqual(saved.created_by, self.user)
        self.assertEqual(saved.status, SavedHeatmap.Status.PROCESSING)
        self.assertEqual(saved.target_widths, [768, 1024])
        mock_task.assert_called_once_with(saved.id)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_create_defaults_consent_blocking_off(self, _mock_task):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {"url": "https://example.com"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data["block_consent_modals"])
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertFalse(saved.block_consent_modals)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_create_persists_consent_blocking_when_enabled(self, _mock_task):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {"url": "https://example.com", "block_consent_modals": True},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["block_consent_modals"])
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertTrue(saved.block_consent_modals)

    @patch("products.web_analytics.backend.api.heatmaps_api.generate_heatmap_screenshot")
    def test_partial_update_consent_toggle_triggers_regenerate(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
            type=SavedHeatmap.Type.SCREENSHOT,
            block_consent_modals=False,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"old")

        r = self.client.patch(
            f"/api/environments/{self.team.id}/saved/{saved.short_id}/",
            {"block_consent_modals": True},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["block_consent_modals"])
        self.assertEqual(r.data["status"], "processing")
        mock_task.delay.assert_called_once_with(saved.id)
        self.assertEqual(HeatmapSnapshot.objects.filter(heatmap=saved).count(), 0)

    def test_content_returns_202_until_snapshot_exists(self):
        saved = SavedHeatmap.objects.create(team=self.team, url="https://example.com", created_by=self.user)
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=1024")
        self.assertEqual(r.status_code, 202)

    def test_content_returns_snapshot_bytes_and_defaults_width(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpegdata1024")
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertTrue(r["Content-Disposition"].endswith('1024.jpg"'))
        self.assertEqual(r.content, b"jpegdata1024")

    def test_content_picks_closest_snapshot_when_exact_missing(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=768, content=b"jpeg768")
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpeg1024")
        # Request 800 should pick 768 (closest)
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=800")
        self.assertEqual(r.status_code, 200)
        self.assertIn('768.jpg"', r["Content-Disposition"])
        self.assertEqual(r.content, b"jpeg768")

    def test_content_returns_501_when_only_content_location_set(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=None, content_location="s3://bucket/key")
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=1024")
        self.assertEqual(r.status_code, 501)

    def test_content_served_increments_metric(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpegdata1024")

        def _served_count() -> float:
            return REGISTRY.get_sample_value("heatmap_screenshot_content_requests_total", {"outcome": "served"}) or 0.0

        before = _served_count()
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=1024")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_served_count() - before, 1)

    def test_saved_list_excludes_deleted_and_includes_created_by(self):
        SavedHeatmap.objects.create(team=self.team, url="https://a.example", created_by=self.user)
        SavedHeatmap.objects.create(team=self.team, url="https://b.example", created_by=self.user, deleted=True)
        r = self.client.get(f"/api/environments/{self.team.id}/saved/")
        self.assertEqual(r.status_code, 200)
        urls = [x["url"] for x in r.data["results"]]
        self.assertIn("https://a.example", urls)
        self.assertNotIn("https://b.example", urls)
        # created_by present
        found = next(x for x in r.data["results"] if x["url"] == "https://a.example")
        self.assertEqual(found["created_by"]["id"], self.user.id)

    @parameterized.expand(
        [
            ("non_integer_limit", {"limit": "abc"}, 400),
            ("non_integer_offset", {"offset": "xyz"}, 400),
            ("non_integer_created_by", {"created_by": "nope"}, 400),
            ("valid_limit", {"limit": 5}, 200),
            ("oversized_limit_does_not_500", {"limit": 100000000}, 200),
        ]
    )
    def test_saved_list_validates_and_bounds_pagination(self, _name, query, expected_status):
        SavedHeatmap.objects.create(team=self.team, url="https://a.example", created_by=self.user)
        r = self.client.get(f"/api/environments/{self.team.id}/saved/", query)
        assert r.status_code == expected_status

    def test_team_isolation_for_content(self):
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other Team"
        )
        other = SavedHeatmap.objects.create(team=other_team, url="https://example.com")
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{other.id}/content/")
        self.assertEqual(r.status_code, 404)

    def test_content_endpoint_accepts_export_renderer_jwt(self):
        # Screenshot exports render the heatmap in a headless browser that
        # authenticates with an EXPORT_RENDERER JWT. This regression test
        # guards against HeatmapScreenshotViewSet dropping that auth class:
        # if it does, the exporter can't fetch the background image and the
        # resulting PNG renders an `<img alt="Heatmap">` placeholder.
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpegdata1024")

        token = encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=5),
            PosthogJwtAudience.EXPORT_RENDERER,
        )
        unauthenticated = APIClient()
        r = unauthenticated.get(
            f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=1024",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(r.content, b"jpegdata1024")

    @patch("products.web_analytics.backend.api.heatmaps_api.generate_heatmap_screenshot")
    def test_retrieve_auto_recovers_stale_processing_heatmap(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.PROCESSING,
            type=SavedHeatmap.Type.SCREENSHOT,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"old")

        # Force updated_at to 15 minutes ago
        SavedHeatmap.objects.filter(id=saved.id).update(updated_at=timezone.now() - timedelta(minutes=15))

        r = self.client.get(f"/api/environments/{self.team.id}/saved/{saved.short_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "processing")

        # Task was re-enqueued
        mock_task.delay.assert_called_once_with(saved.id)

        # Old snapshots were cleaned up
        self.assertEqual(HeatmapSnapshot.objects.filter(heatmap=saved).count(), 0)

    @patch("products.web_analytics.backend.api.heatmaps_api.generate_heatmap_screenshot")
    def test_retrieve_does_not_recover_recent_processing_heatmap(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.PROCESSING,
            type=SavedHeatmap.Type.SCREENSHOT,
        )

        r = self.client.get(f"/api/environments/{self.team.id}/saved/{saved.short_id}/")
        self.assertEqual(r.status_code, 200)

        # Task was NOT re-enqueued (still within threshold)
        mock_task.delay.assert_not_called()

    @patch("products.web_analytics.backend.api.heatmaps_api.generate_heatmap_screenshot")
    def test_regenerate_endpoint_re_enqueues_task(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.FAILED,
            type=SavedHeatmap.Type.SCREENSHOT,
            exception="previous error",
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"old")

        r = self.client.post(f"/api/environments/{self.team.id}/saved/{saved.short_id}/regenerate/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "processing")
        self.assertIsNone(r.data["exception"])

        mock_task.delay.assert_called_once_with(saved.id)
        self.assertEqual(HeatmapSnapshot.objects.filter(heatmap=saved).count(), 0)

    def test_regenerate_rejects_non_screenshot_type(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            type=SavedHeatmap.Type.IFRAME,
        )

        r = self.client.post(f"/api/environments/{self.team.id}/saved/{saved.short_id}/regenerate/")
        self.assertEqual(r.status_code, 400)


class TestSavedHeatmapRegeneratePersonalAPIKeyScopes(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def _auth(self, value: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {value}"}

    def test_regenerate_allowed_with_heatmap_write_scope(self):
        key = self.create_personal_api_key_with_scopes(["heatmap:write"])
        # Use a non-existent short_id; a 404 proves the scope gate was passed.
        url = f"/api/environments/{self.team.id}/saved/nonexistent-short-id/regenerate/"
        r = self.client.post(url, **self._auth(key))
        assert r.status_code != 403, r.json()

    @parameterized.expand(
        [
            ("read_scope_cannot_satisfy_write", ["heatmap:read"]),
            ("unrelated_scope", ["insight:read"]),
            ("no_scopes", []),
        ]
    )
    def test_regenerate_rejected_without_heatmap_write_scope(self, _name: str, scopes: list[str]):
        key = self.create_personal_api_key_with_scopes(scopes)
        url = f"/api/environments/{self.team.id}/saved/nonexistent-short-id/regenerate/"
        r = self.client.post(url, **self._auth(key))
        assert r.status_code == 403, r.json()
