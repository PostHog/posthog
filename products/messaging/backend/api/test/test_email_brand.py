from typing import TYPE_CHECKING

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.api.email_brand import EmailBrandSerializer

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestEmailBrandAPI(APIBaseTest):
    def _url(self, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/email_brand/current/"

    def _patch(self, payload: dict[str, object], team: Team | None = None) -> "_MonkeyPatchedResponse":
        return self.client.patch(self._url(team), payload, format="json")

    def test_first_save_creates_the_brand_and_later_saves_change_only_what_they_send(self, _flag):
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

        created = self._patch(
            {
                "name": "Juniper Studio",
                "primary_color": "#2E7D32",
                "logo_url": "https://app.example.com/uploaded_media/juniper-logo",
                "source": "website",
            }
        )
        assert created.status_code == status.HTTP_200_OK, created.json()
        assert self._patch({"name": "Juniper", "source": "manual"}).status_code == status.HTTP_200_OK

        brand = self.client.get(self._url()).json()
        assert {key: brand[key] for key in ("name", "primary_color", "logo_url", "source")} == {
            "name": "Juniper",
            "primary_color": "#2e7d32",
            "logo_url": "https://app.example.com/uploaded_media/juniper-logo",
            "source": "manual",
        }

    def test_removing_the_logo_keeps_the_rest_of_the_brand(self, _flag):
        self._patch({"name": "Juniper Studio", "logo_url": "https://app.example.com/uploaded_media/juniper-logo"})

        removed = self._patch({"logo_url": None})

        assert removed.status_code == status.HTTP_200_OK, removed.json()
        assert (removed.json()["name"], removed.json()["logo_url"]) == ("Juniper Studio", None)

    def test_environments_of_one_project_share_one_brand_that_other_projects_never_see(self, _flag):
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        other_project = Team.objects.create(organization=self.organization, name="Other project")

        assert self._patch({"name": "Juniper Studio"}, team=environment).status_code == status.HTTP_200_OK
        assert self._patch({"primary_color": "#2e7d32"}, team=self.team).status_code == status.HTTP_200_OK

        for team in (self.team, environment):
            brand = self.client.get(self._url(team)).json()
            assert (brand["name"], brand["primary_color"]) == ("Juniper Studio", "#2e7d32")
        assert self.client.get(self._url(other_project)).status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_an_invalid_value_with_a_field_error_and_saves_nothing(self, _flag):
        response = self._patch({"name": "Juniper Studio", "primary_color": "green"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "primary_color"
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_is_invisible_while_the_branded_starter_flag_is_off(self, flag):
        flag.return_value = False

        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        assert self._patch({"name": "Juniper Studio"}).status_code == status.HTTP_404_NOT_FOUND
        flag.return_value = True
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_flag_evaluation_failure_cannot_create_a_brand(self, flag: Mock) -> None:
        flag.side_effect = RuntimeError("flag unavailable")

        assert self._patch({"name": "Juniper Studio"}).status_code == status.HTTP_404_NOT_FOUND

        flag.side_effect = None
        flag.return_value = True
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.ee
@patch("posthoganalytics.feature_enabled", return_value=True)
class TestEmailBrandAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        AccessControl.objects.create(team=self.team, resource="hog_flow", resource_id=None, access_level="none")

    def _grant(self, access_level: str, resource_id: str | None) -> User:
        user = User.objects.create_and_join(self.organization, f"{access_level}-{resource_id}@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=resource_id,
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )
        return user

    @parameterized.expand(
        [
            ("editor of one workflow", "editor", "workflow-1", status.HTTP_403_FORBIDDEN),
            ("viewer of every workflow", "viewer", None, status.HTTP_403_FORBIDDEN),
            ("editor of every workflow", "editor", None, status.HTTP_200_OK),
        ]
    )
    def test_only_project_wide_workflow_editors_change_the_brand(
        self, _flag, _name: str, access_level: str, resource_id: str | None, expected_status: int
    ) -> None:
        self.client.force_login(self._grant(access_level, resource_id))

        response = self.client.patch(
            f"/api/projects/{self.team.id}/email_brand/current/", {"name": "Juniper Studio"}, format="json"
        )

        assert response.status_code == expected_status, response.json()


class TestEmailBrandValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("named color", {"primary_color": "green"}, "primary_color"),
            ("short hex", {"primary_color": "#2e7"}, "primary_color"),
            ("css injection", {"primary_color": "#2e7d32;background:url(x)"}, "primary_color"),
            ("script logo", {"logo_url": "javascript:alert(1)"}, "logo_url"),
            ("ftp logo", {"logo_url": "ftp://example.com/logo.png"}, "logo_url"),
            ("logo without a host", {"logo_url": "https:///logo.png"}, "logo_url"),
            ("logo with only credentials", {"logo_url": "https://@/logo.png"}, "logo_url"),
            ("logo with a broken host", {"logo_url": "https://[broken/logo.png"}, "logo_url"),
            ("unknown source", {"source": "figma"}, "source"),
        ]
    )
    def test_rejects_an_invalid_value(self, _name: str, payload: dict, field: str) -> None:
        serializer = EmailBrandSerializer(data=payload, partial=True)

        assert not serializer.is_valid()
        assert list(serializer.errors) == [field]

    def test_accepts_a_logo_hosted_on_a_self_hosted_instance_without_a_dotted_domain(self) -> None:
        serializer = EmailBrandSerializer(data={"logo_url": "http://posthog:8000/uploaded_media/logo"}, partial=True)

        assert serializer.is_valid(), serializer.errors
