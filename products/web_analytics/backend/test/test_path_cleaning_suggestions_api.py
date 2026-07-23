from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.health_issue import HealthIssue
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.web_analytics.backend.path_cleaning_suggestions import service
from products.web_analytics.backend.path_cleaning_suggestions.prompts import SuggestedRule, SuggestedRulesResponse

# Mirrors the stored payload shape: no `examples` — real paths never land in health-issue payloads.
RULES = [
    {
        "regex": r"/users/\d+/profile",
        "alias": "/users/<id>/profile",
        "order": 0,
        "reason": "user id",
        "match_count": 3,
    }
]

KIND = "path_cleaning_suggestions"


class TestPathCleaningSuggestionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # apply is project-admin gated (path_cleaning_filters is an admin-only team field), so the
        # default test user is elevated; the non-admin test demotes explicitly.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_path_cleaning_suggestions/{suffix}"

    def _make_suggestion(self, team: Team) -> HealthIssue:
        issue, _ = HealthIssue.upsert_issue(
            team_id=team.id,
            kind=KIND,
            severity=HealthIssue.Severity.INFO,
            payload={"rules": RULES, "model": "claude-haiku-4-5", "sampled_path_count": 4, "distinct_path_count": 500},
            hash_keys=[],
        )
        return issue

    def test_apply_merges_rules_and_resolves_issue(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        suggestion = self._make_suggestion(self.team)

        response = self.client.post(self._url(f"{suggestion.id}/apply/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["applied"], 1)

        self.team.refresh_from_db()
        self.assertEqual(self.team.path_cleaning_filters[0]["regex"], r"/users/\d+/profile")
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, HealthIssue.Status.RESOLVED)

    def test_apply_does_not_overwrite_existing_rules(self) -> None:
        self.team.path_cleaning_filters = [{"regex": r"/keep", "alias": "/keep", "order": 0}]
        self.team.save()
        suggestion = self._make_suggestion(self.team)

        self.client.post(self._url(f"{suggestion.id}/apply/"))
        self.team.refresh_from_db()
        regexes = [f["regex"] for f in self.team.path_cleaning_filters]
        self.assertIn(r"/keep", regexes)
        self.assertIn(r"/users/\d+/profile", regexes)

    @parameterized.expand(
        [
            ("write_scope_allows", ["web_analytics:write"], status.HTTP_200_OK),
            ("read_scope_forbidden", ["web_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_apply_requires_write_scope_for_token_auth(self, _name: str, scopes: list[str], expected: int) -> None:
        # The write actions must declare required_scopes, or personal-API-key / OAuth token access
        # (how the MCP server authenticates) is rejected outright. Session auth bypasses scope
        # checks, so we drop the session and authenticate with a scoped key.
        self.team.path_cleaning_filters = []
        self.team.save()
        suggestion = self._make_suggestion(self.team)
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="mcp",
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        response = self.client.post(self._url(f"{suggestion.id}/apply/"), headers={"authorization": f"Bearer {value}"})
        self.assertEqual(response.status_code, expected)

    def test_apply_requires_project_admin(self) -> None:
        # path_cleaning_filters is admin-gated on the team API; this endpoint must not be a bypass.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.path_cleaning_filters = []
        self.team.save()
        suggestion = self._make_suggestion(self.team)

        response = self.client.post(self._url(f"{suggestion.id}/apply/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.team.refresh_from_db()
        self.assertEqual(self.team.path_cleaning_filters, [])

    def test_generate_stores_health_issue_and_returns_suggestion(self) -> None:
        self.team.path_cleaning_filters = []
        self.team.save()
        llm_response = SuggestedRulesResponse(
            rules=[SuggestedRule(regex=r"/users/\d+/profile", alias="/users/<id>/profile")]
        )
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch.object(service, "count_distinct_pathnames", return_value=500),
            patch.object(service, "sample_pathnames", return_value=[("/users/1/profile", 5), ("/users/2/profile", 3)]),
            patch.object(service, "call_llm_for_rules", return_value=llm_response),
        ):
            response = self.client.post(self._url("generate/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], "generated")
        self.assertEqual(len(body["suggestion"]["rules"]), 1)
        self.assertEqual(body["suggestion"]["rules"][0]["alias"], "/users/<id>/profile")
        issue = HealthIssue.objects.get(team_id=self.team.id, kind=KIND)
        self.assertEqual(issue.status, HealthIssue.Status.ACTIVE)
        self.assertEqual(str(issue.id), body["suggestion"]["id"])

    def test_generate_replaces_previous_active_suggestion(self) -> None:
        # hash_keys=[] means one active suggestion per team — a regeneration must update the
        # existing row, not accumulate stale siblings that shadow each other in list reads.
        self.team.path_cleaning_filters = []
        self.team.save()
        first = self._make_suggestion(self.team)
        llm_response = SuggestedRulesResponse(rules=[SuggestedRule(regex=r"/posts/\d+", alias="/posts/<id>")])
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch.object(service, "count_distinct_pathnames", return_value=500),
            patch.object(service, "sample_pathnames", return_value=[("/posts/1", 5), ("/posts/2", 3)]),
            patch.object(service, "call_llm_for_rules", return_value=llm_response),
        ):
            response = self.client.post(self._url("generate/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(HealthIssue.objects.filter(team_id=self.team.id, kind=KIND).count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.payload["rules"][0]["alias"], "/posts/<id>")

    def test_generate_requires_feature_flag(self) -> None:
        # Dogfooding gate: without the flag, generate must not spend a ClickHouse sample + LLM call.
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(self._url("generate/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_apply_another_teams_suggestion(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        other_suggestion = self._make_suggestion(other_team)

        response = self.client.post(self._url(f"{other_suggestion.id}/apply/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preview_applies_rules_in_order_and_returns_only_changed_paths(self) -> None:
        suggestion = self._make_suggestion(self.team)
        sampled = [("/users/1/profile", 100), ("/about", 40)]
        with patch.object(service, "sample_pathnames", return_value=sampled):
            response = self.client.get(self._url(f"{suggestion.id}/preview/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["sampled_path_count"], 2)
        self.assertEqual(body["changed_path_count"], 1)
        self.assertEqual(
            body["examples"], [{"before": "/users/1/profile", "after": "/users/<id>/profile", "views": 100}]
        )

    def test_preview_allows_read_scope_and_non_admin(self) -> None:
        # The preview modal must work for read-only tokens and plain members — it changes nothing.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        suggestion = self._make_suggestion(self.team)
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="mcp-read",
            secure_value=hash_key_value(value),
            scopes=["web_analytics:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        with patch.object(service, "sample_pathnames", return_value=[("/users/1/profile", 5)]):
            response = self.client.get(
                self._url(f"{suggestion.id}/preview/"), headers={"authorization": f"Bearer {value}"}
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_preview_another_teams_suggestion(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other-preview"))
        other_suggestion = self._make_suggestion(other_team)

        response = self.client.get(self._url(f"{other_suggestion.id}/preview/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
