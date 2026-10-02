import zlib
from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, UploadedMedia
from posthog.models.integration import Integration

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

    @parameterized.expand([("GET", "current/"), ("PATCH", "current/"), ("GET", "suggest_repository/")])
    def test_every_route_is_hidden_while_the_flag_is_off(self, flag, method, route):
        self._patch({"name": "Acme"})
        flag.side_effect = None
        flag.return_value = False

        response = self.client.generic(
            method,
            f"/api/projects/{self.team.id}/email_brand/{route}",
            '{"name": "Globex"}',
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


def _repository(name: str, *, pushed_days_ago: int, language: str = "Go", archived: bool = False) -> dict:
    return {
        "id": zlib.crc32(name.encode()),
        "name": name,
        "full_name": f"acme-labs/{name}",
        "language": language,
        "pushed_at": (timezone.now() - timedelta(days=pushed_days_ago)).isoformat().replace("+00:00", "Z"),
        "archived": archived,
    }


@time_machine.travel("2026-09-15T12:00:00Z", tick=False)
@patch("posthoganalytics.feature_enabled", side_effect=_only_brand_detection_enabled)
class TestEmailBrandRepositorySuggestionAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.name = "Initech"
        self.organization.save()
        self.team.project.name = "Default project"
        self.team.project.save()
        self.team.app_urls = []
        self.team.save()

    def _connect_github(self, repositories: list[dict]) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="4242",
            config={"account": {"name": "acme-labs"}},
            repository_cache=repositories,
            repository_cache_updated_at=timezone.now(),
        )

    def _suggest(self) -> list[dict]:
        response = self.client.get(f"/api/projects/{self.team.id}/email_brand/suggest_repository/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["repositories"]

    @parameterized.expand(
        [
            ("an app url host", {"app_urls": ["https://app.acme-cloud.example"]}),
            ("the project name", {"project_name": "Acme Cloud"}),
            ("the organization name", {"organization_name": "Acme Cloud Inc."}),
        ]
    )
    def test_puts_the_repository_whose_name_matches_the_brand_first(self, _flag, _name, brand):
        if "app_urls" in brand:
            self.team.app_urls = brand["app_urls"]
            self.team.save()
        if "project_name" in brand:
            self.team.project.name = brand["project_name"]
            self.team.project.save()
        if "organization_name" in brand:
            self.organization.name = brand["organization_name"]
            self.organization.save()
        self._connect_github(
            [
                _repository("infra-scripts", pushed_days_ago=1),
                _repository("acme-web", pushed_days_ago=90, language="TypeScript"),
                _repository("acme-legacy-site", pushed_days_ago=0, language="TypeScript", archived=True),
            ]
        )

        suggestions = self._suggest()

        assert [(s["full_name"], s["reasons"]) for s in suggestions] == [
            ("acme-labs/acme-web", ["name_match", "web_language"]),
            ("acme-labs/infra-scripts", ["recent_push"]),
        ]

    def test_without_a_name_match_the_most_recently_pushed_repository_comes_first(self, _flag):
        self.team.app_urls = ["https://www.app.example"]
        self.team.save()
        self._connect_github(
            [
                _repository("billing-service", pushed_days_ago=40),
                _repository("dashboard", pushed_days_ago=2, language="TypeScript"),
                _repository("ml-models", pushed_days_ago=10, language="Python"),
                _repository("default-project-app", pushed_days_ago=60),
            ]
        )

        suggestions = self._suggest()

        assert [(s["full_name"], s["reasons"]) for s in suggestions] == [
            ("acme-labs/dashboard", ["recent_push", "web_language"]),
            ("acme-labs/ml-models", ["recent_push"]),
            ("acme-labs/billing-service", []),
            ("acme-labs/default-project-app", []),
        ]

    def test_ties_keep_one_order_by_full_name_on_every_call(self, _flag):
        pushed_at = "2026-09-01T10:00:00Z"
        tied = [
            {**_repository(name, pushed_days_ago=0), "pushed_at": pushed_at}
            for name in ("zeta-tools", "alpha-tools", "Mid-tools")
        ]
        self._connect_github(tied)

        orders = [[s["full_name"] for s in self._suggest()] for _ in range(2)]

        assert orders == [["acme-labs/alpha-tools", "acme-labs/Mid-tools", "acme-labs/zeta-tools"]] * 2

    def test_without_a_github_integration_of_the_project_returns_no_suggestions(self, _flag):
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        foreign = Integration.objects.create(
            team=other_project,
            kind="github",
            integration_id="777",
            repository_cache=[_repository("acme-web", pushed_days_ago=1)],
            repository_cache_updated_at=timezone.now(),
        )

        for query in ("", f"?integration_id={foreign.id}"):
            response = self.client.get(f"/api/projects/{self.team.id}/email_brand/suggest_repository/{query}")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json() == {"integration_id": None, "repositories": []}

    @patch("posthog.models.github_integration_base.github_request")
    def test_returns_no_suggestions_when_github_cannot_list_an_uncached_installation(self, github_request, _flag):
        github_request.return_value = MagicMock(status_code=503, headers={}, json=lambda: {})
        integration = Integration.objects.create(
            team=self.team, kind="github", integration_id="4242", sensitive_config={"access_token": "fake-token"}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/email_brand/suggest_repository/")

        assert github_request.called
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"integration_id": integration.id, "repositories": []}
