from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, UploadedMedia

BRAND_DETECTION_FLAG = "workflows-brand-detection"


def _only_brand_detection_enabled(flag: str, *args, **kwargs) -> bool:
    return flag == BRAND_DETECTION_FLAG


@patch("posthoganalytics.feature_enabled", side_effect=_only_brand_detection_enabled)
class TestEmailBrandAPI(APIBaseTest):
    def _url(self, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/email_brand/current/"

    def _patch(self, payload: dict, team: Team | None = None):
        return self.client.patch(self._url(team), payload, format="json")

    def test_first_patch_creates_the_brand_and_later_patches_edit_it(self, _flag):
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

        created = self._patch({"name": "Acme", "primary_color": "#1A2B3C", "font_family": "Inter"})
        assert created.status_code == status.HTTP_200_OK, created.json()

        edited = self._patch({"accent_color": "#ff8800"})
        assert edited.status_code == status.HTTP_200_OK, edited.json()

        brand = self.client.get(self._url()).json()
        assert brand["name"] == "Acme"
        assert brand["primary_color"] == "#1a2b3c"
        assert brand["accent_color"] == "#ff8800"
        assert brand["font_family"] == "Inter"
        assert brand["text_color"] == "#111111"
        assert brand["background_color"] == "#ffffff"

    def test_environments_of_one_project_share_a_single_brand(self, _flag):
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        logo = UploadedMedia.objects.create(team=environment, purpose="email", file_name="logo.png")

        named = self._patch({"name": "Acme", "logo": str(logo.id)}, team=environment)
        assert named.status_code == status.HTTP_200_OK, named.json()
        assert self._patch({"primary_color": "#123456"}, team=self.team).status_code == status.HTTP_200_OK

        for team in (self.team, environment):
            brand = self.client.get(self._url(team)).json()
            assert (brand["name"], brand["logo"], brand["primary_color"]) == ("Acme", str(logo.id), "#123456")

    def test_another_project_neither_sees_nor_changes_the_brand(self, _flag):
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        self._patch({"name": "Acme"})

        assert self.client.get(self._url(other_project)).status_code == status.HTTP_404_NOT_FOUND
        assert self._patch({"name": "Globex"}, team=other_project).json()["name"] == "Globex"
        assert self.client.get(self._url()).json()["name"] == "Acme"

    @parameterized.expand(
        [
            ("named color", {"primary_color": "red"}, "primary_color"),
            ("short hex", {"accent_color": "#fff"}, "accent_color"),
            ("non hex digit", {"text_color": "#12345g"}, "text_color"),
            ("missing hash", {"background_color": "ffffff"}, "background_color"),
            ("source for an unknown field", {"sources": {"slogan": {"path": "a", "detected_value": "b"}}}, "sources"),
            ("source without a path", {"sources": {"name": {"detected_value": "Acme"}}}, "sources__name__path"),
            (
                "color source without a detected value",
                {"sources": {"primary_color": {"path": "app/globals.css"}}},
                "sources__primary_color__detected_value",
            ),
        ]
    )
    def test_rejects_invalid_values_with_a_field_error_and_creates_nothing(self, _flag, _name, payload, attr):
        response = self._patch(payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == attr
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_logo_must_be_a_vetted_email_image_of_the_project(self, _flag):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        foreign_logo = UploadedMedia.objects.create(team=other_team, purpose="email", file_name="logo.png")
        unvetted_logo = UploadedMedia.objects.create(
            team=self.team, purpose="email", file_name="logo.png", pending=True
        )
        private_upload = UploadedMedia.objects.create(team=self.team, purpose="desktop_feedback", file_name="shot.png")
        own_logo = UploadedMedia.objects.create(team=self.team, purpose="email", file_name="logo.png")

        for rejected_logo in (foreign_logo, unvetted_logo, private_upload):
            rejected = self._patch({"logo": str(rejected_logo.id)})
            assert rejected.status_code == status.HTTP_400_BAD_REQUEST, rejected.json()
            assert rejected.json()["attr"] == "logo"

        accepted = self._patch({"logo": str(own_logo.id)})
        assert accepted.status_code == status.HTTP_200_OK, accepted.json()
        assert accepted.json()["logo"] == str(own_logo.id)
        assert accepted.json()["logo_url"].endswith(f"/uploaded_media/{own_logo.id}")

    def test_reports_a_value_as_edited_only_when_it_differs_from_its_detected_value(self, _flag):
        response = self._patch(
            {
                "name": "Acme",
                "primary_color": "#445566",
                "accent_color": "#ff8800",
                "sources": {
                    "primary_color": {"path": "app/globals.css", "line": 12, "detected_value": "#112233"},
                    "accent_color": {"path": "tailwind.config.ts", "line": 4, "detected_value": "#FF8800"},
                },
            }
        )

        edited = response.json()["edited"]
        assert edited["primary_color"] is True
        assert edited["accent_color"] is False
        assert edited["name"] is False
        assert response.json()["sources"]["primary_color"]["path"] == "app/globals.css"

    @parameterized.expand([("GET",), ("PATCH",)])
    def test_every_route_is_hidden_while_the_flag_is_off(self, flag, method):
        self._patch({"name": "Acme"})
        flag.side_effect = None
        flag.return_value = False

        response = self.client.generic(method, self._url(), '{"name": "Globex"}', content_type="application/json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
