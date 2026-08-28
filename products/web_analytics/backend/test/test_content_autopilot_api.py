from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.egress.public_web import PublicWebFetchError
from posthog.models import Organization, Team

from products.web_analytics.backend.api.content_autopilot import CONTENT_AUTOPILOT_FEATURE_FLAGS
from products.web_analytics.backend.models import ContentAutopilotProposal, ContentAutopilotRun
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)


class TestContentAutopilotAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.web_analytics.backend.api.content_autopilot.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _profiles_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_profiles/{suffix}"

    def _runs_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_runs/{suffix}"

    def _proposals_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_proposals/{suffix}"

    def _measurements_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_content_autopilot_measurements/{suffix}"

    def _profile_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": "Example",
            "domain": "https://example.com",
            "source_urls": ["https://example.com/sitemap.xml"],
            "content_boundaries": ["/blog"],
            "brand_rules": ["Use sentence case"],
            "search_console_enabled": False,
            "delivery_mode": "export_only",
            "github_repository": "",
            "base_branch": "main",
            "content_directories": [],
            "url_to_file_convention": "",
        }
        payload.update(overrides)
        return payload

    def test_requires_both_rollout_flags_with_user_and_organization_context(self) -> None:
        for disabled_flag in CONTENT_AUTOPILOT_FEATURE_FLAGS:
            with self.subTest(disabled_flag=disabled_flag):
                self.feature_enabled.reset_mock()
                self.feature_enabled.side_effect = lambda flag, *args, disabled_flag=disabled_flag, **kwargs: (
                    flag != disabled_flag
                )

                response = self.client.get(self._profiles_url())

                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                calls_by_flag = {call.args[0]: call for call in self.feature_enabled.call_args_list}
                self.assertEqual(set(calls_by_flag), set(CONTENT_AUTOPILOT_FEATURE_FLAGS))
                for call in calls_by_flag.values():
                    self.assertEqual(call.args[1], self.user.distinct_id)
                    self.assertEqual(call.kwargs["groups"], {"organization": str(self.organization.id)})
                    self.assertEqual(
                        call.kwargs["group_properties"],
                        {"organization": {"id": str(self.organization.id)}},
                    )

    def test_requires_an_authenticated_project_member(self) -> None:
        self.client.logout()

        response = self.client.get(self._profiles_url())

        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

    def test_profile_validates_site_and_delivery_boundaries(self) -> None:
        invalid_payloads = [
            (self._profile_payload(source_urls=["https://other.example/sitemap.xml"]), "source_urls"),
            (self._profile_payload(content_boundaries=["/docs/../private"]), "content_boundaries"),
            (
                self._profile_payload(
                    delivery_mode="github",
                    github_repository="example/site",
                    content_directories=["../content"],
                ),
                "content_directories",
            ),
        ]

        for payload, field in invalid_payloads:
            with self.subTest(field=field):
                response = self.client.post(self._profiles_url(), payload, format="json")

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

    def test_profile_rejects_an_unsafe_github_base_branch(self) -> None:
        response = self.client.post(
            self._profiles_url(),
            self._profile_payload(
                delivery_mode="github",
                github_repository="example/site",
                base_branch="../../pulls",
                content_directories=["content"],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "base_branch")

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

    @patch("products.web_analytics.backend.api.content_autopilot.MAX_CONTENT_AUTOPILOT_SITE_PROFILES", 1)
    def test_project_cannot_exceed_the_site_profile_limit(self) -> None:
        create_content_autopilot_profile(self.team)

        response = self.client.post(
            self._profiles_url(),
            self._profile_payload(
                domain="https://docs.example.com",
                source_urls=["https://docs.example.com/sitemap.xml"],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "domain")

    @patch("products.web_analytics.backend.api.content_autopilot.discover_site")
    def test_discover_returns_editable_onboarding_defaults(self, discover_site: MagicMock) -> None:
        discover_site.return_value = {
            "name": "Example",
            "domain": "https://example.com",
            "source_urls": ["https://example.com/sitemap.xml"],
            "content_boundaries": ["/"],
            "sitemap_detected": True,
            "warnings": [],
        }

        response = self.client.post(
            self._profiles_url("discover/"),
            {"domain": "https://example.com/blog"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["source_urls"], ["https://example.com/sitemap.xml"])

    @patch("products.web_analytics.backend.api.content_autopilot.discover_site")
    def test_discover_returns_a_validation_error_for_a_typed_fetch_failure(self, discover_site: MagicMock) -> None:
        discover_site.side_effect = PublicWebFetchError("The site could not be inspected safely.")

        response = self.client.post(
            self._profiles_url("discover/"),
            {"domain": "https://example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "domain")

    def test_start_and_cancel_expose_durable_run_transitions(self) -> None:
        profile = create_content_autopilot_profile(self.team)

        started = self.client.post(self._runs_url("start/"), {"profile_id": str(profile.id)}, format="json")
        canceled = self.client.post(self._runs_url(f"{started.json()['id']}/cancel/"), format="json")

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
        edited_package = {**edited_proposal.content_package, "markdown": "# Stale draft"}

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
        self.assertEqual(rejected.json()["lifecycle_status"], ContentAutopilotProposal.LifecycleStatus.REJECTED)
        self.assertEqual(regenerated.json()["lifecycle_status"], ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(
            regenerated.json()["generation_history"][0]["proposed_markdown"], "# Improved guide\n\nUseful content."
        )

    def test_export_returns_markdown_and_updates_delivery_state(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
        )

        response = self.client.post(self._proposals_url(f"{proposal.id}/export/"), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["filename"], "example.md")
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.EXPORTED)
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.DELIVERED)

    def test_open_pull_request_writes_only_the_approved_content_file(self) -> None:
        profile = create_content_autopilot_profile(
            self.team,
            delivery_mode="github",
            github_repository="example/site",
            content_directories=["content"],
        )
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
        )
        github = MagicMock()
        github.organization.return_value = "example"
        github.commit_files_to_branch.return_value = {
            "success": True,
            "commit_sha": "abc123",
            "created_branch": True,
        }
        github.create_pull_request.return_value = {
            "success": True,
            "pr_url": "https://github.com/example/site/pull/7",
        }
        github.find_pull_request_for_branch.return_value = {"success": True, "pr_url": ""}

        with patch(
            "products.web_analytics.backend.content_autopilot.delivery.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            response = self.client.post(
                self._proposals_url("open_pull_request/"),
                {"proposal_ids": [str(proposal.id)]},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(
            github.commit_files_to_branch.call_args.args[3],
            {"content/guides/example.md": proposal.proposed_markdown},
        )

    def test_open_pull_request_requires_integration_write_scope(self) -> None:
        key = self.create_personal_api_key_with_scopes(["web_analytics:write"])
        self.client.logout()

        response = self.client.post(
            self._proposals_url("open_pull_request/"),
            {"proposal_ids": ["00000000-0000-4000-8000-000000000001"]},
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("integration:write", response.json()["detail"])

    def test_other_team_records_are_not_exposed(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other_profile = create_content_autopilot_profile(other_team, domain="https://other.example")
        other_run = create_content_autopilot_run(other_team, other_profile)
        other_proposal = create_content_autopilot_proposal(other_team, other_run)

        proposal_response = self.client.get(self._proposals_url(f"{other_proposal.id}/"))
        measurements_response = self.client.get(self._measurements_url())

        self.assertEqual(proposal_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(measurements_response.status_code, status.HTTP_200_OK)
        self.assertEqual(measurements_response.json()["results"], [])
