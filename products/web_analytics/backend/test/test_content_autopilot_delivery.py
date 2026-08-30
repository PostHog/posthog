from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.web_analytics.backend.content_autopilot.delivery import (
    ContentAutopilotDeliveryError,
    _validated_file_path,
    export_proposal,
    open_pull_request,
)
from products.web_analytics.backend.content_autopilot.lifecycle import ContentAutopilotLifecycleError
from products.web_analytics.backend.models import ContentAutopilotProposal
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)


class TestContentAutopilotDelivery(BaseTest):
    def _github_profile_and_proposal(self, *, file_path: str = "content/guides/example.md") -> ContentAutopilotProposal:
        profile = create_content_autopilot_profile(
            self.team,
            delivery_mode="github",
            github_repository="example/site",
            content_directories=["content"],
        )
        return create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            file_path=file_path,
        )

    def test_file_path_stays_inside_a_configured_markdown_directory(self) -> None:
        self.assertEqual(_validated_file_path("content/guides/example.mdx", ["content"]), "content/guides/example.mdx")

        for file_path in [
            "../secrets.md",
            "/content/example.md",
            "content/./example.md",
            "content\\example.md",
            "scripts/example.py",
            "other/example.md",
        ]:
            with self.subTest(file_path=file_path), self.assertRaises(ContentAutopilotDeliveryError):
                _validated_file_path(file_path, ["content"])

    def test_export_returns_markdown_and_records_delivery(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))

        filename, markdown, content_package = export_proposal(proposal=proposal)

        self.assertEqual(filename, "example.md")
        self.assertEqual(markdown, proposal.proposed_markdown)
        self.assertEqual(content_package, proposal.content_package)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.EXPORTED)
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.DELIVERED)

    def test_export_rejects_a_proposal_that_failed_blocking_validation(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            validation_passed=False,
        )

        with self.assertRaises(ContentAutopilotLifecycleError):
            export_proposal(proposal=proposal)

        proposal.refresh_from_db()
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.NOT_DELIVERED)

    def test_pull_request_writes_only_the_validated_content_file(self) -> None:
        proposal = self._github_profile_and_proposal()
        github = MagicMock()
        github.organization.return_value = "example"
        github.commit_files_to_branch.return_value = {"success": True, "commit_sha": "abc123"}
        github.create_pull_request.return_value = {
            "success": True,
            "pr_url": "https://github.com/example/site/pull/7",
        }

        with patch(
            "products.web_analytics.backend.content_autopilot.delivery.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            pull_request_url, branch = open_pull_request(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        self.assertEqual(pull_request_url, "https://github.com/example/site/pull/7")
        self.assertTrue(branch.startswith("posthog/content-autopilot-"))
        self.assertEqual(
            github.commit_files_to_branch.call_args.args[3],
            {"content/guides/example.md": proposal.proposed_markdown},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.PR_OPENED)

    def test_pull_request_rejects_a_generated_path_outside_the_boundary(self) -> None:
        proposal = self._github_profile_and_proposal(file_path=".github/workflows/publish.yml")
        github = MagicMock()
        github.organization.return_value = "example"

        with (
            patch(
                "products.web_analytics.backend.content_autopilot.delivery.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ),
            self.assertRaises(ContentAutopilotDeliveryError),
        ):
            open_pull_request(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        github.commit_files_to_branch.assert_not_called()
        proposal.refresh_from_db()
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.FAILED)

    def test_delivery_uses_the_run_snapshot_after_profile_settings_change(self) -> None:
        proposal = self._github_profile_and_proposal()
        run = proposal.run
        run.input_snapshot = {
            "delivery_mode": "github",
            "github_repository": "example/site",
            "base_branch": "release",
            "content_directories": ["content"],
        }
        run.save(update_fields=["input_snapshot"])
        profile = run.profile
        profile.github_repository = "example/other"
        profile.base_branch = "main"
        profile.content_directories = ["other"]
        profile.save(update_fields=["github_repository", "base_branch", "content_directories"])
        github = MagicMock()
        github.organization.return_value = "example"
        github.commit_files_to_branch.return_value = {"success": True, "commit_sha": "abc123"}
        github.create_pull_request.return_value = {
            "success": True,
            "pr_url": "https://github.com/example/site/pull/7",
        }

        with patch(
            "products.web_analytics.backend.content_autopilot.delivery.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ) as integration_lookup:
            open_pull_request(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        integration_lookup.assert_called_once_with(self.team.id, "example/site", source="content_autopilot")
        self.assertEqual(github.commit_files_to_branch.call_args.args[2], "release")

    def test_integration_lookup_failure_is_recorded_as_retryable_delivery_state(self) -> None:
        proposal = self._github_profile_and_proposal()

        with (
            patch(
                "products.web_analytics.backend.content_autopilot.delivery.GitHubIntegration.first_for_team_repository",
                side_effect=RuntimeError("Integration unavailable"),
            ),
            self.assertRaises(ContentAutopilotDeliveryError),
        ):
            open_pull_request(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        proposal.refresh_from_db()
        self.assertEqual(proposal.delivery_state, ContentAutopilotProposal.DeliveryState.FAILED)
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)
        self.assertEqual(proposal.delivery_error, "Could not deliver the selected proposals to GitHub.")
