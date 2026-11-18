import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import OrganizationMembership
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

from products.web_analytics.backend.models.heatmap_capture_config_version import HeatmapCaptureConfigVersion
from products.web_analytics.backend.models.heatmap_saved import SavedHeatmap
from products.web_analytics.backend.presentation.views.capture_settings import HeatmapCaptureSettingsRequestSerializer

INSERT_HEATMAP_EVENT = """
INSERT INTO sharded_heatmaps (session_id, team_id, distinct_id, timestamp, x, y, scale_factor,
    viewport_width, viewport_height, pointer_target_fixed, current_url, type)
SELECT %(session_id)s, %(team_id)s, 'u', %(timestamp)s, 10, 20, 16, 100, 100, 1, %(current_url)s, 'click'
"""


class TestCaptureUrlValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("example.com/pricing",),
            ("www.example.com",),
            ("/pricing",),
            ("ftp://example.com",),
            ("",),
        ]
    )
    def test_rejects_non_http_urls(self, url: str) -> None:
        serializer = HeatmapCaptureSettingsRequestSerializer(data={"url_allowlist": [url]})
        assert not serializer.is_valid()

    def test_normalizes_and_deduplicates(self) -> None:
        serializer = HeatmapCaptureSettingsRequestSerializer(
            data={"url_allowlist": [" https://example.com/b ", "https://example.com/b", "https://example.com/a/*"]}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["url_allowlist"] == ["https://example.com/a/*", "https://example.com/b"]


class TestCaptureSettings(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/heatmap_capture/settings/"

    def test_non_admin_cannot_write(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch(self._url(), {"capture_mode": "all", "url_allowlist": []}, format="json")
        assert response.status_code == 403

    def test_get_returns_paid_defaults(self) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        response = self.client.get(self._url())
        assert response.status_code == 200
        assert response.json() == {
            "capture_mode": "all",
            "url_allowlist": [],
            "enforcement_enabled": False,
            "can_capture_all_urls": True,
            "capture_url_limit": None,
        }

    def test_get_returns_free_defaults(self) -> None:
        self.organization.has_active_subscription = False
        self.organization.save()
        response = self.client.get(self._url())
        assert response.status_code == 200
        assert response.json() == {
            "capture_mode": "url_allowlist",
            "url_allowlist": [],
            "enforcement_enabled": False,
            "can_capture_all_urls": False,
            "capture_url_limit": 3,
        }

    def test_free_org_cannot_capture_all_or_exceed_limit(self) -> None:
        self.organization.has_active_subscription = False
        self.organization.save()
        assert self.client.patch(self._url(), {"capture_mode": "all"}, format="json").status_code == 400
        four = [f"https://example.com/{i}" for i in range(4)]
        assert (
            self.client.patch(
                self._url(), {"capture_mode": "url_allowlist", "url_allowlist": four}, format="json"
            ).status_code
            == 400
        )
        assert (
            self.client.patch(
                self._url(), {"capture_mode": "url_allowlist", "url_allowlist": four[:3]}, format="json"
            ).status_code
            == 200
        )

    def test_paid_org_can_capture_all(self) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        response = self.client.patch(self._url(), {"capture_mode": "all", "url_allowlist": []}, format="json")
        assert response.status_code == 200
        assert response.json()["capture_mode"] == "all"

    def test_free_org_get_suggests_oldest_saved_heatmaps(self) -> None:
        self.organization.has_active_subscription = False
        self.organization.save()
        for i, url in enumerate(["https://ex.com/a", "https://ex.com/b", "https://ex.com/c", "https://ex.com/d"]):
            with time_machine.travel(f"2025-01-0{i + 1}", tick=False):
                SavedHeatmap.objects.create(team=self.team, url=url)
        with time_machine.travel("2025-01-05", tick=False):
            for _ in range(101):
                SavedHeatmap.objects.create(team=self.team, url="https://ex.com/a")

        body = self.client.get(self._url()).json()
        assert body["capture_mode"] == "url_allowlist"
        assert body["url_allowlist"] == ["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"]
        assert HeatmapCaptureConfigVersion.objects.for_team(self.team.pk).count() == 0
        assert not TeamHeatmapConfig.objects.filter(team=self.team).exists()

    def test_downgraded_org_reads_clamped_settings(self) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        four = [f"https://example.com/{i}" for i in range(4)]
        assert (
            self.client.patch(self._url(), {"capture_mode": "all", "url_allowlist": four}, format="json").status_code
            == 200
        )
        SavedHeatmap.objects.create(team=self.team, url="https://ex.com/a")

        self.organization.has_active_subscription = False
        self.organization.save()
        body = self.client.get(self._url()).json()
        assert body["capture_mode"] == "url_allowlist"
        assert body["url_allowlist"] == ["https://ex.com/a"]
        assert body["can_capture_all_urls"] is False

        response = self.client.patch(self._url(), {"url_allowlist": ["https://ex.com/b"]}, format="json")
        assert response.status_code == 200
        assert response.json() == {
            "capture_mode": "url_allowlist",
            "url_allowlist": ["https://ex.com/b"],
            "enforcement_enabled": False,
            "can_capture_all_urls": False,
            "capture_url_limit": 3,
        }
        config = TeamHeatmapConfig.objects.get(team=self.team)
        assert config.capture_mode == "url_allowlist"
        assert config.capture_url_allowlist == ["https://ex.com/b"]

    def test_paid_org_gets_no_suggestion(self) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        SavedHeatmap.objects.create(team=self.team, url="https://ex.com/a")
        assert self.client.get(self._url()).json()["url_allowlist"] == []
        assert HeatmapCaptureConfigVersion.objects.for_team(self.team.pk).count() == 0

    @override_settings(HEATMAP_URL_ALLOWLIST_ENFORCEMENT_ENABLED=True)
    def test_get_reflects_enforcement_setting(self) -> None:
        assert self.client.get(self._url()).json()["enforcement_enabled"] is True

    def test_patch_saves_and_records_a_version(self) -> None:
        response = self.client.patch(
            self._url(),
            {"capture_mode": "url_allowlist", "url_allowlist": ["https://example.com/pricing"]},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["url_allowlist"] == ["https://example.com/pricing"]

        config = TeamHeatmapConfig.objects.get(team=self.team)
        assert config.capture_mode == "url_allowlist"
        assert config.capture_url_allowlist == ["https://example.com/pricing"]

        versions = HeatmapCaptureConfigVersion.objects.for_team(self.team.pk)
        assert versions.count() == 1
        version = versions.get()
        assert version.effective_to is None
        assert version.patterns == ["https://example.com/pricing"]

    def test_second_patch_soft_closes_prior_version(self) -> None:
        self.client.patch(
            self._url(), {"capture_mode": "url_allowlist", "url_allowlist": ["https://example.com/a"]}, format="json"
        )
        self.client.patch(self._url(), {"capture_mode": "all", "url_allowlist": []}, format="json")

        versions = HeatmapCaptureConfigVersion.objects.for_team(self.team.pk).order_by("effective_from")
        assert versions.count() == 2
        first, second = versions
        assert first.effective_to is not None
        assert first.patterns == ["https://example.com/a"]
        assert second.effective_to is None
        assert second.mode == "all"
        assert second.patterns == []

    def test_unchanged_patch_records_no_new_version(self) -> None:
        body = {"capture_mode": "url_allowlist", "url_allowlist": ["https://example.com/a"]}
        self.client.patch(self._url(), body, format="json")
        self.client.patch(self._url(), body, format="json")
        assert HeatmapCaptureConfigVersion.objects.for_team(self.team.pk).count() == 1


class TestCapturePages(APIBaseTest, ClickhouseTestMixin):
    def _create_heatmap_event(self, session_id: str, current_url: str, timestamp: str) -> None:
        ClickhouseProducer().produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_HEATMAP_EVENT,
            data={
                "session_id": session_id,
                "team_id": self.team.pk,
                "timestamp": format_clickhouse_timestamp(timestamp),
                "current_url": current_url,
            },
        )

    @time_machine.travel("2025-03-31", tick=False)
    def test_pages_lists_top_urls_by_recent_volume(self) -> None:
        self._create_heatmap_event("s1", "https://example.com/pricing", "2025-03-30T09:00:00")
        self._create_heatmap_event("s2", "https://example.com/pricing", "2025-03-30T10:00:00")
        self._create_heatmap_event("s3", "https://example.com/blog", "2025-03-30T11:00:00")
        self._create_heatmap_event("s4", "https://example.com/old", "2025-01-01T09:00:00")

        pages = self.client.get(f"/api/projects/{self.team.id}/heatmap_capture/pages/").json()["pages"]
        urls = [p["url"] for p in pages]
        assert urls == ["https://example.com/pricing", "https://example.com/blog"]
        assert pages[0]["count"] == 2
