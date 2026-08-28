from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.lifecycle import (
    DELIVERY_CLAIM_LEASE,
    ContentAutopilotLifecycleError,
    cancel_run,
    claim_proposals_for_delivery,
    edit_proposal,
    regenerate_proposal,
    reject_proposal,
    start_run,
)
from products.web_analytics.backend.models import (
    ContentAutopilotMeasurement,
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
        proposal = create_content_autopilot_proposal(self.team, run)
        ContentAutopilotMeasurement.objects.for_team(self.team.id).create(team=self.team, proposal=proposal)

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        create_content_autopilot_profile(other_team, domain="https://other.example")

        for model in [
            ContentAutopilotSiteProfile,
            ContentAutopilotRun,
            ContentAutopilotProposal,
            ContentAutopilotMeasurement,
        ]:
            with self.subTest(model=model.__name__), self.assertRaises(TeamScopeError):
                model.objects.count()

        self.assertEqual(ContentAutopilotSiteProfile.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(ContentAutopilotSiteProfile.objects.for_team(other_team.id).count(), 1)

    def test_each_site_has_its_own_active_run_boundary(self) -> None:
        first_profile = create_content_autopilot_profile(self.team, search_console_enabled=True)
        second_profile = create_content_autopilot_profile(self.team, domain="https://docs.example.com")

        first_run = start_run(team=self.team, profile_id=str(first_profile.id), triggered_by_id=self.user.id)

        self.assertEqual(first_run.input_snapshot["domain"], "https://example.com")
        self.assertEqual(first_run.input_snapshot["confidence"], "standard")
        self.assertEqual(first_run.input_snapshot["source_urls"], first_profile.source_urls)
        self.assertEqual(first_run.input_snapshot["content_boundaries"], first_profile.content_boundaries)
        self.assertEqual(first_run.input_snapshot["delivery_mode"], first_profile.delivery_mode)
        self.assertEqual(first_run.input_snapshot["base_branch"], first_profile.base_branch)
        self.assertEqual(first_run.input_snapshot["content_directories"], first_profile.content_directories)
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

    def test_edit_invalidates_validation_and_delivery_state(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        proposal.delivery_state = ContentAutopilotProposal.DeliveryState.DELIVERED
        proposal.delivery_reference = "previous.md"
        proposal.save(update_fields=["delivery_state", "delivery_reference"])

        edited = edit_proposal(
            proposal=proposal,
            proposed_markdown="# Reviewed draft",
            content_package={**proposal.content_package, "markdown": "# Stale draft"},
        )

        self.assertEqual(edited.content_package["markdown"], "# Reviewed draft")
        self.assertEqual(edited.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(edited.validation_report, {"passed": False, "checks": []})
        self.assertEqual(edited.delivery_state, ContentAutopilotProposal.DeliveryState.NOT_DELIVERED)
        self.assertEqual(edited.delivery_reference, "")

    def test_regeneration_archives_the_previous_attempt_and_caps_history(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        proposal.generation_history = [{"attempt": attempt} for attempt in range(20)]
        proposal.save(update_fields=["generation_history"])

        regenerated = regenerate_proposal(proposal=proposal)

        self.assertEqual(regenerated.lifecycle_status, ContentAutopilotProposal.LifecycleStatus.GENERATING)
        self.assertEqual(len(regenerated.generation_history), 20)
        self.assertEqual(regenerated.generation_history[0], {"attempt": 1})
        self.assertEqual(regenerated.generation_history[-1]["proposed_markdown"], proposal.proposed_markdown)
        self.assertEqual(regenerated.generation_history[-1]["content_package"]["markdown"], "")
        self.assertTrue(regenerated.generation_history[-1]["validation_report"]["passed"])

    def test_regeneration_bounds_archived_markdown(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        proposal.generation_history = [{"proposed_markdown": str(index) * 400_000} for index in range(3)]
        proposal.save(update_fields=["generation_history"])

        regenerated = regenerate_proposal(proposal=proposal)

        self.assertLessEqual(
            sum(len(str(entry.get("proposed_markdown") or "")) for entry in regenerated.generation_history),
            1_000_000,
        )
        self.assertEqual(regenerated.generation_history[-1]["proposed_markdown"], proposal.proposed_markdown)

    def test_delivery_claim_can_recover_after_its_lease_expires(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        proposal = create_content_autopilot_proposal(self.team, create_content_autopilot_run(self.team, profile))
        ContentAutopilotProposal.objects.for_team(self.team.id).filter(id=proposal.id).update(
            delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERING,
            updated_at=timezone.now(),
        )

        with self.assertRaises(ContentAutopilotLifecycleError):
            claim_proposals_for_delivery(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        ContentAutopilotProposal.objects.for_team(self.team.id).filter(id=proposal.id).update(
            updated_at=timezone.now() - DELIVERY_CLAIM_LEASE,
        )

        claimed = claim_proposals_for_delivery(team_id=self.team.id, proposal_ids=[str(proposal.id)])

        self.assertEqual(claimed[0].delivery_state, ContentAutopilotProposal.DeliveryState.DELIVERING)

    def test_delivery_claim_accepts_five_improvements_from_one_run(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        run = create_content_autopilot_run(self.team, profile)
        proposals = [
            create_content_autopilot_proposal(self.team, run, file_path=f"content/page-{index}.md")
            for index in range(5)
        ]

        claimed = claim_proposals_for_delivery(
            team_id=self.team.id,
            proposal_ids=[str(proposal.id) for proposal in proposals],
        )

        self.assertEqual(len(claimed), 5)
        self.assertTrue(
            all(proposal.delivery_state == ContentAutopilotProposal.DeliveryState.DELIVERING for proposal in claimed)
        )

    def test_delivery_claim_rejects_new_content_batches_and_unvalidated_proposals(self) -> None:
        profile = create_content_autopilot_profile(self.team)
        run = create_content_autopilot_run(self.team, profile)
        new_content = create_content_autopilot_proposal(
            self.team,
            run,
            proposal_type=ContentAutopilotProposal.ProposalType.NEW_CONTENT,
        )
        improvement = create_content_autopilot_proposal(self.team, run, file_path="content/improvement.md")

        with self.assertRaises(ContentAutopilotLifecycleError):
            claim_proposals_for_delivery(
                team_id=self.team.id,
                proposal_ids=[str(new_content.id), str(improvement.id)],
            )

        improvement.validation_report = {"passed": False, "checks": []}
        improvement.save(update_fields=["validation_report"])
        with self.assertRaises(ContentAutopilotLifecycleError):
            claim_proposals_for_delivery(team_id=self.team.id, proposal_ids=[str(improvement.id)])
