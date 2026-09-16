from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.web_analytics.backend.presentation.views.screenshot_settings import (
    HeatmapScreenshotSettingsRequestSerializer,
)


class TestScreenshotHostnames(SimpleTestCase):
    @parameterized.expand(
        [
            ("https://example.com",),
            ("*.example.com",),
            ("example.com:443",),
            ("127.0.0.1",),
            ("[::1]",),
            ("localhost",),
            ("example.com/path",),
            ("example.com.",),
            ("a..example.com",),
            ("-a.example.com",),
            ("a_.example.com",),
            ("user@example.com",),
            ("0x7f.1",),
            ("0x7f.0x0.0x0.0x1",),
            ("example.com?x",),
        ]
    )
    def test_rejects_non_hostnames(self, hostname: str) -> None:
        serializer = HeatmapScreenshotSettingsRequestSerializer(data={"allowed_hostnames": [hostname]})
        assert not serializer.is_valid()

    def test_normalizes_and_deduplicates_exact_hostnames(self) -> None:
        serializer = HeatmapScreenshotSettingsRequestSerializer(
            data={"allowed_hostnames": [" WWW.Example.com ", "www.example.com", "bücher.example", "tenant.github.io"]}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["allowed_hostnames"] == [
            "tenant.github.io",
            "www.example.com",
            "xn--bcher-kva.example",
        ]


class TestScreenshotSettings(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config = TeamHeatmapConfig.objects.create(team=self.team, screenshot_secret="phh_synthetic_test_secret")

    def _url(self, alias: str = "projects", team_id: int | None = None) -> str:
        return f"/api/{alias}/{team_id or self.team.id}/heatmap_screenshot/settings/"

    def _set_rbac(self, enabled: bool) -> None:
        self.organization.available_product_features = (
            [
                {"key": feature, "name": feature}
                for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
            ]
            if enabled
            else []
        )
        self.organization.save()
        if enabled:
            AccessControl.objects.update_or_create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                defaults={"access_level": "member"},
            )

    @parameterized.expand([(False, False), (False, True), (True, False), (True, True)])
    def test_permissions_and_secret_masking(self, rbac: bool, admin: bool) -> None:
        self._set_rbac(rbac)
        self.organization_membership.level = (
            OrganizationMembership.Level.ADMIN if admin else OrganizationMembership.Level.MEMBER
        )
        self.organization_membership.save()
        for alias in ("projects", "environments"):
            response = self.client.get(self._url(alias))
            assert response.status_code == 200, response.json()
            assert response.json()["has_secret"] is True
            assert "phh_synthetic_test_secret" not in response.content.decode()
            response = self.client.patch(self._url(alias), {"allowed_hostnames": ["www.example.com"]})
            assert response.status_code == (200 if admin else 403), response.json()
            team_response = self.client.get(f"/api/{alias}/{self.team.id}/")
            assert team_response.json()["heatmaps_screenshot_secret"] == (
                self.config.screenshot_secret if admin else None
            )
        self.config.refresh_from_db()
        assert self.config.allowed_hostnames == (["www.example.com"] if admin else [])

    @parameterized.expand([False, True])
    def test_empty_patch_does_not_create_or_change_config(self, configured: bool) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        if configured:
            self.config.allowed_hostnames = ["www.example.com"]
            self.config.save(update_fields=["allowed_hostnames"])
        else:
            self.config.delete()
        logs_before = ActivityLog.objects.filter(team_id=self.team.id).count()

        response = self.client.patch(self._url(), {})

        assert response.status_code == 200, response.json()
        assert response.json() == {
            "allowed_hostnames": ["www.example.com"] if configured else [],
            "has_secret": configured,
            "cookie_delivery_enabled": False,
        }
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == logs_before
        if configured:
            self.config.refresh_from_db()
            assert self.config.allowed_hostnames == ["www.example.com"]
            assert self.config.screenshot_secret == "phh_synthetic_test_secret"
        else:
            assert not TeamHeatmapConfig.objects.filter(team_id=self.team.id).exists()

    def test_updates_log_hostnames_without_disclosing_secret(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(self._url(), {"allowed_hostnames": ["WWW.Example.com"]})
        assert response.status_code == 200, response.json()
        log = ActivityLog.objects.filter(team_id=self.team.id, scope="Team").latest("created_at")
        assert log.detail is not None
        assert log.detail["changes"] == [
            {
                "type": "Team",
                "action": "changed",
                "field": "heatmaps_screenshot_allowed_hostnames",
                "before": [],
                "after": ["www.example.com"],
            }
        ]
        assert self.config.screenshot_secret not in str(log.detail)
        assert self.client.patch(self._url(), {"allowed_hostnames": []}).status_code == 200
        self.config.refresh_from_db()
        assert self.config.allowed_hostnames == []

    def test_cannot_read_or_modify_another_organization(self) -> None:
        other = Team.objects.create(organization=Organization.objects.create(name="Other test organization"))
        TeamHeatmapConfig.objects.create(team=other, allowed_hostnames=["other.example"])
        for alias in ("projects", "environments"):
            assert self.client.get(self._url(alias, other.id)).status_code == 403
            assert self.client.patch(self._url(alias, other.id), {"allowed_hostnames": []}).status_code == 403
        assert TeamHeatmapConfig.objects.get(team_id=other.id).allowed_hostnames == ["other.example"]

    @parameterized.expand([("project:read", 403), ("project:write", 200)])
    def test_api_token_scopes_gate_updates(self, scope: str, expected_status: int) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Screenshot test",
            secure_value=hash_key_value(token),
            scopes=[scope],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        headers = {"authorization": f"Bearer {token}"}
        assert self.client.get(self._url(), headers=headers).status_code == 200
        response = self.client.patch(self._url(), {"allowed_hostnames": ["www.example.com"]}, headers=headers)
        assert response.status_code == expected_status, response.json()

    def test_member_cannot_access_a_denied_project_in_the_same_organization(self) -> None:
        self._set_rbac(True)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        other = Team.objects.create(organization=self.organization)
        AccessControl.objects.create(team=other, resource="project", resource_id=str(other.id), access_level="none")
        assert self.client.get(self._url(team_id=other.id)).status_code == 403
        assert (
            self.client.patch(self._url(team_id=other.id), {"allowed_hostnames": ["attacker.example"]}).status_code
            == 403
        )
