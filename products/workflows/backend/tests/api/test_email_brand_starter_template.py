from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import UploadedMedia

from products.messaging.backend.api.design_validation import validate_design
from products.messaging.backend.models import MessageTemplate

BRAND_DETECTION_FLAG = "workflows-brand-detection"
RENDERED_HTML = "<html><body>Rendered by Unlayer</body></html>"


def _only_brand_detection_enabled(flag: str, *args, **kwargs) -> bool:
    return flag == BRAND_DETECTION_FLAG


def _contents(design: dict) -> list[dict]:
    return [content for row in design["body"]["rows"] for column in row["columns"] for content in column["contents"]]


def _content(design: dict, content_id: str) -> dict:
    return next(content for content in _contents(design) if content["id"] == content_id)


@patch("posthoganalytics.feature_enabled", side_effect=_only_brand_detection_enabled)
@override_settings(UNLAYER_API_KEY="test-key")
class TestEmailBrandStarterTemplateAPI(APIBaseTest):
    def _brand_url(self, route: str) -> str:
        return f"/api/projects/{self.team.id}/email_brand/{route}/"

    def _save_brand(self, **values) -> None:
        response = self.client.patch(self._brand_url("current"), values, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def _starter_design(self) -> dict:
        response = self.client.get(self._brand_url("starter_design"))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _create_starter_template(self):
        return self.client.post(self._brand_url("create_starter_template"))

    def _logo(self) -> UploadedMedia:
        return UploadedMedia.objects.create(team=self.team, purpose="email", file_name="logo.png")

    def test_starter_design_carries_the_brand_values(self, _flag):
        logo = self._logo()
        self._save_brand(
            name="Acme",
            logo=str(logo.id),
            primary_color="#1d4aff",
            accent_color="#f54e00",
            text_color="#222222",
            background_color="#fafafa",
            font_family="Montserrat",
            font_stack="Montserrat, Arial, sans-serif",
        )

        starter = self._starter_design()
        design = starter["design"]

        assert validate_design(design) == []
        assert starter["name"] == "Acme starter template"
        assert "Acme" in starter["subject"]
        logo_block = _content(design, "brand-starter-logo")
        assert logo_block["values"]["src"]["url"].endswith(f"/uploaded_media/{logo.id}")
        assert logo_block["values"]["altText"] == "Acme"
        header_column = design["body"]["rows"][0]["columns"][0]
        assert header_column["values"]["border"]["borderTopColor"] == "#f54e00"
        cta_colors = _content(design, "brand-starter-cta")["values"]["buttonColors"]
        assert (cta_colors["backgroundColor"], cta_colors["color"]) == ("#1d4aff", "#ffffff")
        assert _content(design, "brand-starter-body-text")["values"]["color"] == "#222222"
        assert {row["values"]["backgroundColor"] for row in design["body"]["rows"]} == {"#fafafa"}
        assert design["body"]["values"]["fontFamily"] == {
            "label": "Montserrat",
            "value": "'Montserrat',sans-serif",
            "url": "https://fonts.googleapis.com/css?family=Montserrat:400,700",
        }
        assert (
            "{{ unsubscribe_url }}"
            in _content(design, "brand-starter-unsubscribe")["values"]["unsubscribe_link_content"]
        )

    def test_brand_without_a_logo_shows_its_name_as_the_header(self, _flag):
        self._save_brand(name="Acme")

        design = self._starter_design()["design"]

        assert validate_design(design) == []
        assert not [content for content in _contents(design) if content["type"] == "image"]
        header = design["body"]["rows"][0]["columns"][0]["contents"]
        assert [(content["type"], content["values"]["text"]) for content in header] == [("heading", "Acme")]

    @patch("products.workflows.backend.presentation.views.email_brand.render_design_html", return_value=RENDERED_HTML)
    def test_creates_a_template_that_later_brand_edits_leave_unchanged(self, render: MagicMock, _flag):
        self._save_brand(name="Acme", primary_color="#1d4aff")
        design = self._starter_design()["design"]

        response = self._create_starter_template()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        template_url = f"/api/environments/{self.team.id}/messaging_templates/{response.json()['template_id']}/"
        created = self.client.get(template_url).json()
        assert created["name"] == "Acme starter template"
        assert created["description"] == "Created from your Email brand."
        assert created["content"]["email"]["design"] == design
        assert created["content"]["email"]["html"] == RENDERED_HTML
        assert created["content"]["email"]["subject"]
        render.assert_called_once_with(design)

        self._save_brand(name="Globex", primary_color="#00aa55")

        assert self.client.get(template_url).json()["content"] == created["content"]

    @override_settings(UNLAYER_API_KEY="")
    def test_without_an_unlayer_key_creation_asks_for_the_editor_and_creates_nothing(self, _flag):
        self._save_brand(name="Acme")

        response = self._create_starter_template()

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.json()
        assert response.json()["code"] == "design_rendering_unavailable"
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()

    @parameterized.expand([("starter_design", "GET"), ("create_starter_template", "POST")])
    def test_routes_are_hidden_while_the_flag_is_off(self, flag, route, method):
        self._save_brand(name="Acme")
        flag.side_effect = None
        flag.return_value = False

        response = self.client.generic(method, self._brand_url(route))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([("starter_design", "GET"), ("create_starter_template", "POST")])
    def test_routes_need_a_saved_brand(self, _flag, route, method):
        response = self.client.generic(method, self._brand_url(route))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not MessageTemplate.objects.filter(team_id=self.team.id).exists()
