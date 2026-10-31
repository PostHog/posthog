from collections.abc import Callable
from contextlib import nullcontext
from typing import Any
from urllib.parse import urlparse

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

import httpx
from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.security.url_validation import PinnedUrlVerdict

from products.access_control.backend.facade.testing import create_access_control
from products.error_tracking.backend.logic.sentry_migration import client as sentry_client
from products.error_tracking.backend.models import ErrorTrackingSettings, ErrorTrackingSuppressionRule

TOKEN = "sntryu_test_token_value"
PROJECT_PATH = "/api/0/projects/acme/web/"


def _response(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(status_code, json=body, headers=headers)


def _no_more_pages(cursor: str = "0:100:0") -> dict[str, str]:
    return {"Link": f'<https://sentry.io/x>; rel="next"; results="false"; cursor="{cursor}"'}


PROJECT_RESPONSES: dict[str, Callable[[], httpx.Response]] = {
    PROJECT_PATH: _response(
        {
            "slug": "web",
            "options": {
                "filters:error_messages": "*ResizeObserver loop*\nTypeError: Failed to fetch*",
                "filters:releases": "",
                "filters:blacklisted_ips": "",
                "filters:react-hydration-errors": False,
                "filters:chunk-load-error": False,
            },
        }
    ),
    f"{PROJECT_PATH}filters/": _response(
        [
            {"id": "browser-extensions", "active": False},
            {"id": "legacy-browsers", "active": ["ie", "safari"]},
            {"id": "localhost", "active": True},
            {"id": "web-crawlers", "active": False},
        ]
    ),
    f"{PROJECT_PATH}keys/": _response(
        [
            {"id": "key1", "label": "Default", "isActive": True, "rateLimit": {"window": 3600, "count": 5000}},
            {"id": "key2", "label": "Backend", "isActive": True, "rateLimit": {"window": 60, "count": 100}},
            {"id": "key3", "label": "Old", "isActive": False, "rateLimit": {"window": 60, "count": 1}},
        ],
        headers=_no_more_pages(),
    ),
}


class TestSentryMigrationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.requested: list[tuple[str, str | None]] = []

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/sentry_migration/{action}/"

    def _fake_sentry(self, routes: dict[str, Callable[[], httpx.Response]]) -> Callable[..., httpx.Client]:
        def handle(request: httpx.Request) -> httpx.Response:
            url = urlparse(str(request.url))
            self.requested.append((f"{url.scheme}://{url.netloc}{url.path}", request.headers.get("Authorization")))
            route = f"{url.path}?{url.query}" if url.query else url.path
            return routes[route]() if route in routes else httpx.Response(404, json={"detail": "not found"})

        def client(url: str, pinned_ips: object, **kwargs: Any) -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=kwargs["follow_redirects"])

        return client

    def _post(self, action: str, routes: dict[str, Callable[[], httpx.Response]], body: dict) -> Any:
        with (
            patch(
                f"{sentry_client.__name__}.validate_url_and_pin_ips",
                return_value=PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=set()),
            ),
            patch(f"{sentry_client.__name__}.pinned_client", side_effect=self._fake_sentry(routes)),
        ):
            return self.client.post(self._url(action), {"auth_token": TOKEN, **body}, format="json")

    def _project_body(self, **extra: object) -> dict:
        return {"organization_slug": "acme", "project_slug": "web", **extra}

    def test_projects_follow_pagination_and_keep_the_token_on_the_sentry_host(self) -> None:
        routes = {
            "/api/0/organizations/": _response(
                [
                    {"slug": "acme", "name": "Acme", "links": {"regionUrl": "https://de.sentry.io"}},
                    {"slug": "rogue", "name": "Rogue", "links": {"regionUrl": "https://sentry.example.com"}},
                ],
                headers=_no_more_pages(),
            ),
            "/api/0/organizations/acme/projects/": _response(
                [
                    {"slug": "web", "name": "Web", "platform": "javascript"},
                    {"slug": "secret", "name": "Secret", "platform": "python", "hasAccess": False},
                ],
                headers={"Link": '<https://de.sentry.io/x>; rel="next"; results="true"; cursor="0:100:0"'},
            ),
            "/api/0/organizations/acme/projects/?cursor=0%3A100%3A0": _response(
                [{"slug": "api", "name": "API", "platform": "python"}], headers=_no_more_pages("0:200:0")
            ),
            "/api/0/organizations/rogue/projects/": _response([{"slug": "app", "name": "App"}]),
        }

        response = self._post("projects", routes, {})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(p["organization_slug"], p["project_slug"]) for p in response.json()["projects"]] == [
            ("acme", "web"),
            ("acme", "api"),
            ("rogue", "app"),
        ]
        assert {(url, auth) for url, auth in self.requested} == {
            ("https://sentry.io/api/0/organizations/", f"Bearer {TOKEN}"),
            ("https://de.sentry.io/api/0/organizations/acme/projects/", f"Bearer {TOKEN}"),
            ("https://sentry.io/api/0/organizations/rogue/projects/", f"Bearer {TOKEN}"),
        }

    @parameterized.expand(
        [
            (401, "didn't accept the token"),
            (403, "org:read and project:read"),
            (429, "Try again in 30 seconds"),
        ]
    )
    def test_sentry_errors_become_a_message_without_the_token(self, sentry_status: int, message: str) -> None:
        routes = {
            "/api/0/organizations/": _response(
                {"detail": "nope"}, status_code=sentry_status, headers={"Retry-After": "30"}
            )
        }

        response = self._post("projects", routes, {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert TOKEN not in response.content.decode()

    @parameterized.expand(
        [
            ("plain_http_url", {"base_url": "http://sentry.example.com"}, None, "https://", 0),
            ("malformed_url", {"base_url": "https://[sentry.example.com"}, None, "https://", 0),
            ("more_pages_than_allowed", {}, ("MAX_PAGES", 1), "more Sentry data than PostHog can read", 1),
            ("slower_than_the_total_budget", {}, ("TOTAL_TIMEOUT_SECONDS", 0), "took too long", 0),
        ]
    )
    def test_connection_limits_return_a_message_instead_of_partial_results(
        self, _name: str, body: dict, client_override: tuple[str, int] | None, message: str, requests_sent: int
    ) -> None:
        routes = {
            "/api/0/organizations/": _response(
                [{"slug": "acme", "name": "Acme"}],
                headers={"Link": '<https://sentry.io/x>; rel="next"; results="true"; cursor="0:100:0"'},
            )
        }
        override = patch.object(sentry_client, *client_override) if client_override else nullcontext()

        with override:
            response = self._post("projects", routes, body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert len(self.requested) == requests_sent

    def test_preview_then_apply_imports_only_the_selected_items(self) -> None:
        preview = self._post("preview", PROJECT_RESPONSES, self._project_body())

        assert preview.status_code == status.HTTP_200_OK, preview.json()
        items = {item["sentry_value"]: item for item in preview.json()["items"]}
        assert set(items) == {
            "5,000 events per 1 hour",
            "100 events per 1 minute",
            "*ResizeObserver loop*",
            "TypeError: Failed to fetch*",
            "Internet Explorer, Older versions of Safari",
            "On",
        }
        assert not any(item["already_in_posthog"] for item in items.values())
        selected = [
            items["5,000 events per 1 hour"]["id"],
            items["*ResizeObserver loop*"]["id"],
            items["On"]["id"],
        ]

        applied = self._post("apply", PROJECT_RESPONSES, self._project_body(item_ids=selected))

        assert applied.status_code == status.HTTP_200_OK, applied.json()
        assert applied.json() == {
            "suppression_rules_created": 1,
            "built_in_filters_enabled": 1,
            "rate_limit_updated": True,
        }
        rules = ErrorTrackingSuppressionRule.objects.filter(team=self.team)
        assert [rule.filters for rule in rules.filter(built_in_key__isnull=True)] == [
            items["*ResizeObserver loop*"]["suppression_rule_filters"]
        ]
        assert list(rules.filter(built_in_key__isnull=False).values_list("built_in_key", flat=True)) == ["localhost"]
        settings = ErrorTrackingSettings.objects.get(team=self.team)
        assert (settings.project_rate_limit_value, settings.project_rate_limit_bucket_size_minutes) == (5000, 60)

        second_preview = self._post("preview", PROJECT_RESPONSES, self._project_body())

        second_items = {item["id"]: item for item in second_preview.json()["items"]}
        assert {item_id for item_id, item in second_items.items() if item["already_in_posthog"]} == set(selected)
        assert (
            "replaces the project's current rate limit of 5,000 exceptions per 1 hour"
            in (second_items["rate_limit:key2:100:60"]["note"])
        )

        repeated = self._post("apply", PROJECT_RESPONSES, self._project_body(item_ids=selected))

        assert repeated.json() == {
            "suppression_rules_created": 0,
            "built_in_filters_enabled": 0,
            "rate_limit_updated": False,
        }
        assert ErrorTrackingSuppressionRule.objects.filter(team=self.team).count() == 2

    @parameterized.expand(
        [
            ("sampled_rule", "*ResizeObserver loop*", {"sampling_rate": 0.5}),
            ("disabled_rule", "*ResizeObserver loop*", {"disabled_data": {"message": "Rule failed to run"}}),
            (
                "disabled_automatic_rule",
                "On",
                {"built_in_key": "localhost", "disabled_data": {"message": "Rule failed to run"}},
            ),
        ]
    )
    def test_preview_only_counts_rules_that_drop_every_match(
        self, _name: str, sentry_value: str, rule_fields: dict
    ) -> None:
        preview = self._post("preview", PROJECT_RESPONSES, self._project_body())
        item = next(i for i in preview.json()["items"] if i["sentry_value"] == sentry_value)
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team, filters=item["suppression_rule_filters"] or {}, bytecode=[], order_key=0, **rule_fields
        )

        second_preview = self._post("preview", PROJECT_RESPONSES, self._project_body())

        same_item = next(i for i in second_preview.json()["items"] if i["id"] == item["id"])
        assert not same_item["already_in_posthog"]

    @parameterized.expand(
        [
            ("two_rate_limits", ["rate_limit:key1:5000:3600", "rate_limit:key2:100:60"], "Select only one rate limit"),
            ("rate_limit_changed_since_preview", ["rate_limit:key1:1:3600"], "Load the preview again"),
            ("item_not_in_sentry", ["error_message:000000000000"], "Load the preview again"),
            ("inactive_key", ["rate_limit:key3:1:60"], "Load the preview again"),
        ]
    )
    def test_apply_rejects_selections_it_cannot_import(self, _name: str, item_ids: list[str], message: str) -> None:
        response = self._post("apply", PROJECT_RESPONSES, self._project_body(item_ids=item_ids))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert not ErrorTrackingSuppressionRule.objects.filter(team=self.team).exists()
        assert not ErrorTrackingSettings.objects.filter(team=self.team, project_rate_limit_value__isnull=False).exists()

    def test_apply_names_a_pattern_posthog_cannot_compile_and_writes_nothing(self) -> None:
        routes = {
            **PROJECT_RESPONSES,
            PROJECT_PATH: _response(
                {"slug": "web", "options": {"filters:error_messages": "*ResizeObserver loop*\n[z-a]"}}
            ),
        }
        preview = self._post("preview", routes, self._project_body())
        message_ids = [item["id"] for item in preview.json()["items"] if item["category"] == "error_message"]

        applied = self._post("apply", routes, self._project_body(item_ids=message_ids))

        assert applied.status_code == status.HTTP_400_BAD_REQUEST
        assert '"[z-a]"' in applied.json()["detail"]
        assert not ErrorTrackingSuppressionRule.objects.filter(team=self.team).exists()

    @pytest.mark.ee
    def test_import_requires_resource_level_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        restricted_user = User.objects.create_and_join(self.organization, "restricted@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=restricted_user, organization=self.organization)
        create_access_control(team_id=self.team.id, resource="error_tracking", access_level="none")
        create_access_control(
            team_id=self.team.id,
            resource="error_tracking",
            resource_id="00000000-0000-0000-0000-000000000001",
            access_level="editor",
            organization_member_id=membership.id,
        )
        self.client.force_login(restricted_user)

        response = self._post("apply", PROJECT_RESPONSES, self._project_body(item_ids=["inbound_filter:localhost"]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not ErrorTrackingSuppressionRule.objects.filter(team=self.team).exists()
