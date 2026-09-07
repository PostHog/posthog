from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.rate_limit import ContentAutopilotDiscoveryBurstRateThrottle

from products.web_analytics.backend.models import ContentAutopilotProposal, ContentAutopilotRun
from products.web_analytics.backend.presentation.views.content_autopilot import CONTENT_AUTOPILOT_FEATURE_FLAG
from products.web_analytics.backend.public_url_fetch import FetchedPublicUrl, PublicUrlFetchError
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)

DISCOVERED_SITE = {
    "name": "Example",
    "domain": "https://example.com",
    "source_urls": ["https://example.com/sitemap.xml"],
    "content_boundaries": ["/"],
    "sitemap_detected": True,
    "warnings": [],
}


class TestContentAutopilotAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.web_analytics.backend.presentation.views.content_autopilot.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _profiles_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_profiles/{suffix}"

    def _runs_url(self, suffix: str = "", *, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/web_analytics_content_autopilot_runs/{suffix}"

    def _proposals_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_proposals/{suffix}"

    def _profile_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": "Example",
            "domain": "https://example.com",
            "source_urls": ["https://example.com/sitemap.xml"],
            "content_boundaries": ["/blog"],
            "brand_rules": ["Use sentence case"],
            "search_console_enabled": False,
        }
        payload.update(overrides)
        return payload

    def test_requires_the_rollout_flag_with_user_and_organization_context(self) -> None:
        self.feature_enabled.return_value = False

        response = self.client.get(self._profiles_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.feature_enabled.assert_called_once_with(
            CONTENT_AUTOPILOT_FEATURE_FLAG,
            self.user.distinct_id,
            organization_id=str(self.organization.id),
        )

    def test_requires_an_authenticated_project_member(self) -> None:
        self.client.logout()

        response = self.client.get(self._profiles_url())

        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

    @parameterized.expand(
        [
            ("source_urls", {"source_urls": ["https://other.example/sitemap.xml"]}),
            ("content_boundaries", {"content_boundaries": ["/docs/../private"]}),
        ]
    )
    def test_profile_validates_site_boundaries(self, field: str, overrides: dict[str, object]) -> None:
        response = self.client.post(self._profiles_url(), self._profile_payload(**overrides), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], field)

    def test_profile_accepts_same_origin_sources_with_queries_and_default_ports(self) -> None:
        response = self.client.post(
            self._profiles_url(),
            self._profile_payload(source_urls=["https://example.com:443/sitemap.xml?page=1"]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["source_urls"], ["https://example.com:443/sitemap.xml?page=1"])

    def test_project_can_configure_and_list_multiple_sites(self) -> None:
        first = self.client.post(self._profiles_url(), self._profile_payload(), format="json")
        second = self.client.post(
            self._profiles_url(),
            self._profile_payload(
                name="Docs",
                domain="https://docs.example.com/",
                source_urls=["https://docs.example.com/sitemap.xml"],
            ),
            format="json",
        )

        response = self.client.get(self._profiles_url())

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.json())
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.json())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {profile["domain"] for profile in response.json()["results"]},
            {"https://example.com", "https://docs.example.com"},
        )

    def test_project_cannot_configure_the_same_domain_twice(self) -> None:
        create_content_autopilot_profile(self.team)

        response = self.client.post(self._profiles_url(), self._profile_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "domain")

    @patch("products.web_analytics.backend.presentation.views.content_autopilot.discover_site")
    def test_discover_returns_editable_onboarding_defaults(self, discover_site: MagicMock) -> None:
        discover_site.return_value = DISCOVERED_SITE

        response = self.client.post(
            self._profiles_url("discover/"),
            {"domain": "https://example.com/blog"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["source_urls"], ["https://example.com/sitemap.xml"])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_discovered_defaults_create_a_profile_when_the_sitemap_redirects(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **_kwargs: object) -> FetchedPublicUrl:
            if url == "https://example.com/sitemap.xml":
                return FetchedPublicUrl(
                    status_code=301,
                    headers={"location": "https://www.example.com/sitemap.xml"},
                    body=b"",
                )
            if url == "https://www.example.com/sitemap.xml":
                return FetchedPublicUrl(status_code=200, headers={}, body=b"<urlset />")
            return FetchedPublicUrl(status_code=404, headers={}, body=b"")

        fetch_public_url.side_effect = response_for

        discovered = self.client.post(
            self._profiles_url("discover/"),
            {"domain": "https://example.com"},
            format="json",
        )
        created = self.client.post(
            self._profiles_url(),
            {**discovered.json(), "brand_rules": ["Use sentence case"]},
            format="json",
        )

        self.assertEqual(discovered.status_code, status.HTTP_200_OK, discovered.json())
        self.assertTrue(discovered.json()["sitemap_detected"])
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json())
        self.assertEqual(created.json()["source_urls"], ["https://example.com/sitemap.xml"])

    @patch("products.web_analytics.backend.presentation.views.content_autopilot.discover_site")
    def test_discover_returns_a_validation_error_for_a_typed_fetch_failure(self, discover_site: MagicMock) -> None:
        discover_site.side_effect = PublicUrlFetchError("transport", "The site could not be inspected safely.")

        response = self.client.post(
            self._profiles_url("discover/"),
            {"domain": "https://example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "domain")

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.web_analytics.backend.presentation.views.content_autopilot.discover_site")
    def test_discover_is_throttled_for_the_session_authenticated_ui(
        self, discover_site: MagicMock, _rate_limit_enabled: MagicMock
    ) -> None:
        discover_site.return_value = DISCOVERED_SITE
        cache.clear()
        self.addCleanup(cache.clear)

        with patch.object(ContentAutopilotDiscoveryBurstRateThrottle, "rate", "2/minute"):
            statuses = [
                self.client.post(self._profiles_url("discover/"), {"domain": "https://example.com"}).status_code
                for _ in range(3)
            ]

        self.assertEqual(statuses, [status.HTTP_200_OK, status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS])

    def _child_environment(self) -> Team:
        return Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="Child environment",
        )

    @parameterized.expand([("root_project", False), ("child_environment", True)])
    def test_start_and_cancel_expose_durable_run_transitions(self, _name: str, through_child: bool) -> None:
        profile = create_content_autopilot_profile(self.team)
        team_id = self._child_environment().id if through_child else self.team.id

        started = self.client.post(
            self._runs_url("start/", team_id=team_id), {"profile_id": str(profile.id)}, format="json"
        )
        canceled = self.client.post(self._runs_url(f"{started.json()['id']}/cancel/", team_id=team_id), format="json")

        self.assertEqual(started.status_code, status.HTTP_202_ACCEPTED, started.json())
        self.assertEqual(started.json()["input_snapshot"]["confidence"], "lower")
        self.assertEqual(canceled.status_code, status.HTTP_200_OK, canceled.json())
        self.assertEqual(canceled.json()["run_status"], ContentAutopilotRun.RunStatus.CANCELED)

    def test_run_and_proposal_filters_are_validated_and_tenant_scoped(self) -> None:
        first_profile = create_content_autopilot_profile(self.team)
        second_profile = create_content_autopilot_profile(self.team, domain="https://docs.example.com")
        first_run = create_content_autopilot_run(self.team, first_profile)
        second_run = create_content_autopilot_run(self.team, second_profile)
        first_proposal = create_content_autopilot_proposal(self.team, first_run)
        create_content_autopilot_proposal(self.team, second_run)

        runs = self.client.get(self._runs_url(), {"profile_id": str(first_profile.id)})
        proposals = self.client.get(self._proposals_url(), {"run_id": str(first_run.id)})
        invalid_runs = self.client.get(self._runs_url(), {"profile_id": "not-a-uuid"})
        invalid_proposals = self.client.get(self._proposals_url(), {"run_id": "not-a-uuid"})

        self.assertEqual([run["id"] for run in runs.json()["results"]], [str(first_run.id)])
        self.assertEqual([proposal["id"] for proposal in proposals.json()["results"]], [str(first_proposal.id)])
        self.assertEqual(proposals.json()["results"][0]["file_path"], "content/guides/example.md")
        self.assertEqual(proposals.json()["results"][0]["evidence"][0]["opportunity_kind"], "poor_ctr")
        self.assertNotIn("proposed_markdown", proposals.json()["results"][0])
        self.assertNotIn("content_package", proposals.json()["results"][0])
        proposal_detail = self.client.get(self._proposals_url(f"{first_proposal.id}/"))
        self.assertIn("proposed_markdown", proposal_detail.json())
        self.assertIn("content_package", proposal_detail.json())
        self.assertEqual(invalid_runs.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_proposals.status_code, status.HTTP_400_BAD_REQUEST)

    def test_edit_reject_and_regenerate_expose_review_transitions(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        run = create_content_autopilot_run(self.team, profile)
        edited_proposal = create_content_autopilot_proposal(self.team, run)
        rejected_proposal = create_content_autopilot_proposal(self.team, run)
        regenerated_proposal = create_content_autopilot_proposal(self.team, run)
        edited_package = {**edited_proposal.content_package, "title": "Reviewed guide", "markdown": "# Stale draft"}

        edited = self.client.post(
            self._proposals_url(f"{edited_proposal.id}/edit/"),
            {"proposed_markdown": "# Reviewed draft", "content_package": edited_package},
            format="json",
        )
        rejected = self.client.post(self._proposals_url(f"{rejected_proposal.id}/reject/"), format="json")
        regenerated = self.client.post(
            self._proposals_url(f"{regenerated_proposal.id}/regenerate/"),
            format="json",
        )

        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.json())
        self.assertFalse(edited.json()["validation_report"]["passed"])
        self.assertEqual(edited.json()["proposed_markdown"], "# Reviewed draft")
        self.assertEqual(edited.json()["content_package"]["title"], "Reviewed guide")
        self.assertNotIn("markdown", edited.json()["content_package"])
        self.assertEqual(rejected.json()["lifecycle_status"], ContentAutopilotProposal.LifecycleStatus.REJECTED)
        self.assertEqual(regenerated.json()["lifecycle_status"], ContentAutopilotProposal.LifecycleStatus.GENERATING)

    def test_edit_stores_markdown_whitespace_exactly(self) -> None:
        proposal = self._reviewable_proposal()
        markdown = "    indented code block\n\n# Reviewed draft\n\nUseful content.\n"

        edited = self.client.post(
            self._proposals_url(f"{proposal.id}/edit/"),
            {"proposed_markdown": markdown, "content_package": proposal.content_package},
            format="json",
        )

        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.json())
        self.assertEqual(edited.json()["proposed_markdown"], markdown)
        proposal.refresh_from_db()
        self.assertEqual(proposal.proposed_markdown, markdown)

    def _reviewable_proposal(self, *, validation_passed: bool = True) -> ContentAutopilotProposal:
        run = create_content_autopilot_run(self.team, create_content_autopilot_profile(self.team))
        return create_content_autopilot_proposal(self.team, run, validation_passed=validation_passed)

    def test_export_returns_markdown_and_marks_the_proposal_exported(self) -> None:
        proposal = self._reviewable_proposal()

        response = self.client.post(self._proposals_url(f"{proposal.id}/export/"), format="json")
        body = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK, body)
        self.assertEqual(body["filename"], "example.md")
        self.assertEqual(body["markdown"], proposal.proposed_markdown)
        self.assertNotIn("markdown", body["content_package"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.EXPORTED)

    def test_export_refuses_a_proposal_that_failed_validation(self) -> None:
        proposal = self._reviewable_proposal(validation_passed=False)

        response = self.client.post(self._proposals_url(f"{proposal.id}/export/"), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)

    def test_other_team_records_are_not_exposed(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other_profile = create_content_autopilot_profile(other_team, domain="https://other.example")
        other_run = create_content_autopilot_run(other_team, other_profile)
        other_proposal = create_content_autopilot_proposal(other_team, other_run)

        proposal_response = self.client.get(self._proposals_url(f"{other_proposal.id}/"))
        runs_response = self.client.get(self._runs_url())

        self.assertEqual(proposal_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(runs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(runs_response.json()["results"], [])
