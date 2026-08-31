from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.lifecycle import (
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

        canceled = cancel_run(run=run)
        rejected = reject_proposal(proposal=proposal)

        self.assertEqual(canceled.run_status, ContentAutopilotRun.RunStatus.CANCELED)
        self.assertIsNotNone(canceled.completed_at)
        self.assertEqual(rejected.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.REJECTED)
        with self.assertRaises(ContentAutopilotLifecycleError):
            cancel_run(run=canceled)
        with self.assertRaises(ContentAutopilotLifecycleError):
            reject_proposal(proposal=rejected)

    def test_edit_keeps_markdown_single_sourced_and_invalidates_validation(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))

        edited = edit_proposal(
            proposal=proposal,
            proposed_markdown="# Reviewed draft",
            content_package={**proposal.content_package, "markdown": "# Stale draft"},
        )

        self.assertNotIn("markdown", edited.content_package)
        self.assertEqual(edited.proposed_markdown, "# Reviewed draft")
        self.assertEqual(edited.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(edited.validation_report, {"passed": False, "checks": []})

    @parameterized.expand(
        [
            ("ready_for_review", ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW, True),
            ("failed", ContentAutopilotProposal.LifecycleStatus.FAILED, True),
            ("rejected", ContentAutopilotProposal.LifecycleStatus.REJECTED, False),
            ("generating", ContentAutopilotProposal.LifecycleStatus.GENERATING, False),
        ]
    )
    def test_regeneration_accepts_only_reviewed_or_failed_drafts(
        self, _name: str, lifecycle_status: str, is_allowed: bool
    ) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        proposal.lifecycle_status = lifecycle_status
        proposal.save(update_fields=["lifecycle_status"])

        if not is_allowed:
            with self.assertRaises(ContentAutopilotLifecycleError):
                regenerate_proposal(proposal=proposal)
            return

        regenerated = regenerate_proposal(proposal=proposal)
        self.assertEqual(regenerated.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(regenerated.validation_report, {"passed": False, "checks": []})
