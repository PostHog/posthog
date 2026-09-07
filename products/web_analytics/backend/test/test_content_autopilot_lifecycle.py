from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.lifecycle import (
    MAX_PROPOSAL_MARKDOWN_CHARS,
    ContentAutopilotLifecycleError,
    cancel_run,
    edit_proposal,
    regenerate_proposal,
    reject_proposal,
    start_run,
)
from products.web_analytics.backend.models import (
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_profile,
    create_content_autopilot_proposal,
    create_content_autopilot_run,
)


class TestContentAutopilotLifecycle(BaseTest):
    def test_models_fail_closed_and_explicit_scopes_do_not_cross_teams(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        run = create_content_autopilot_run(self.team, profile)
        create_content_autopilot_proposal(self.team, run)

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        create_content_autopilot_profile(other_team, domain="https://other.example")

        for model in [
            ContentAutopilotSiteProfile,
            ContentAutopilotRun,
            ContentAutopilotProposal,
        ]:
            with self.subTest(model=model.__name__), self.assertRaises(TeamScopeError):
                model.objects.count()

        self.assertEqual(ContentAutopilotSiteProfile.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(ContentAutopilotSiteProfile.objects.for_team(other_team.id).count(), 1)

        with self.assertRaisesRegex(ValueError, "same team as its profile"):
            create_content_autopilot_run(other_team, profile)
        with self.assertRaisesRegex(ValueError, "same team as its run"):
            create_content_autopilot_proposal(other_team, run)

        proposal = create_content_autopilot_proposal(self.team, run)
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "could not be found"):
            reject_proposal(team=other_team, proposal_id=str(proposal.id))
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "could not be found"):
            cancel_run(team=other_team, run_id=str(run.id))
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "Select a site"):
            start_run(team=other_team, profile_id=str(profile.id), triggered_by_id=self.user.id)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW)

    def test_each_site_has_its_own_active_run_boundary(self) -> None:
        first_profile = create_content_autopilot_profile(self.team, search_console_enabled=True)
        second_profile = create_content_autopilot_profile(self.team, domain="https://docs.example.com")

        first_run = start_run(team=self.team, profile_id=str(first_profile.id), triggered_by_id=self.user.id)

        self.assertEqual(first_run.input_snapshot["domain"], "https://example.com")
        self.assertEqual(first_run.input_snapshot["confidence"], "standard")
        self.assertEqual(first_run.input_snapshot["source_urls"], first_profile.source_urls)
        self.assertEqual(first_run.input_snapshot["content_boundaries"], first_profile.content_boundaries)
        with self.assertRaises(ContentAutopilotLifecycleError, msg="a duplicate run must not be created"):
            start_run(team=self.team, profile_id=str(first_profile.id), triggered_by_id=self.user.id)

        second_run = start_run(team=self.team, profile_id=str(second_profile.id), triggered_by_id=self.user.id)
        self.assertEqual(second_run.profile_id, second_profile.id)

    def test_cancel_and_reject_only_allow_reviewable_states(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        run = create_content_autopilot_run(self.team, profile)
        proposal = create_content_autopilot_proposal(self.team, run)

        canceled = cancel_run(team=self.team, run_id=str(run.id))
        rejected = reject_proposal(team=self.team, proposal_id=str(proposal.id))

        self.assertEqual(canceled.run_status, ContentAutopilotRun.RunStatus.CANCELED)
        self.assertIsNotNone(canceled.completed_at)
        self.assertEqual(rejected.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.REJECTED)
        with self.assertRaises(ContentAutopilotLifecycleError):
            cancel_run(team=self.team, run_id=str(canceled.id))
        with self.assertRaises(ContentAutopilotLifecycleError):
            reject_proposal(team=self.team, proposal_id=str(rejected.id))

    def test_edit_keeps_markdown_single_sourced_and_invalidates_validation(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))

        edited = edit_proposal(
            team=self.team,
            proposal_id=str(proposal.id),
            proposed_markdown="# Reviewed draft",
            content_package={**proposal.content_package, "markdown": "# Stale draft"},
        )

        self.assertNotIn("markdown", edited.content_package)
        self.assertEqual(edited.proposed_markdown, "# Reviewed draft")
        self.assertEqual(edited.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(edited.validation_report, {"passed": False, "checks": []})

    @parameterized.expand(
        [
            ("ready_for_review", ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW),
            ("failed", ContentAutopilotProposal.LifecycleStatus.FAILED),
        ]
    )
    def test_regeneration_accepts_reviewed_or_failed_drafts(self, _name: str, lifecycle_status: str) -> None:
        regenerated = regenerate_proposal(
            team=self.team, proposal_id=str(self._proposal_with_status(lifecycle_status).id)
        )

        self.assertEqual(regenerated.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(regenerated.validation_report, {"passed": False, "checks": []})

    @parameterized.expand(
        [
            ("rejected", ContentAutopilotProposal.LifecycleStatus.REJECTED),
            ("generating", ContentAutopilotProposal.LifecycleStatus.GENERATING),
        ]
    )
    def test_regeneration_refuses_other_drafts(self, _name: str, lifecycle_status: str) -> None:
        with self.assertRaises(ContentAutopilotLifecycleError):
            regenerate_proposal(team=self.team, proposal_id=str(self._proposal_with_status(lifecycle_status).id))

    @parameterized.expand(
        [
            (
                "rejected draft",
                ContentAutopilotProposal.LifecycleStatus.REJECTED,
                "# Reviewed draft",
                "ready for review can be edited",
            ),
            (
                "generating draft",
                ContentAutopilotProposal.LifecycleStatus.GENERATING,
                "# Reviewed draft",
                "ready for review can be edited",
            ),
            (
                "oversized Markdown",
                ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW,
                "x" * (MAX_PROPOSAL_MARKDOWN_CHARS + 1),
                "characters or fewer",
            ),
        ]
    )
    def test_edit_refuses_invalid_requests(
        self, _name: str, lifecycle_status: str, proposed_markdown: str, expected_error: str
    ) -> None:
        proposal = self._proposal_with_status(lifecycle_status)

        with self.assertRaisesRegex(ContentAutopilotLifecycleError, expected_error):
            edit_proposal(
                team=self.team,
                proposal_id=str(proposal.id),
                proposed_markdown=proposed_markdown,
                content_package=proposal.content_package,
            )

        proposal.refresh_from_db()
        self.assertEqual(proposal.lifecycle_status, lifecycle_status)
        self.assertEqual(proposal.proposed_markdown, "# Improved guide\n\nUseful content.")

    def _proposal_with_status(self, lifecycle_status: str) -> ContentAutopilotProposal:
        profile = create_content_autopilot_profile(self.team)
        return create_content_autopilot_proposal(
            self.team,
            create_content_autopilot_run(self.team, profile),
            lifecycle_status=lifecycle_status,
        )
