from typing import Literal
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import OrganizationMembership, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    ReviewerControl,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    WorkClaim,
)
from products.signals.backend.assignment_flags import assignment_side_effects_allowed, assignment_writer_enabled
from products.signals.backend.assignment_service import (
    AssignmentClaimConflict,
    AssignmentOperationConflict,
    AssignmentProposal,
    AssignmentWriteError,
    ReportAssignmentService,
    StaleAssignmentProposal,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.scout_harness.tools.report import set_scout_report_reviewers
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers, sync_suggested_reviewer_index


class TestReportAssignmentService(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.assignment_service.assignment_writer_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.effects = patch(
            "products.signals.backend.assignment_service.assignment_side_effects_enabled", return_value=False
        )
        self.effects.start()
        self.addCleanup(self.effects.stop)
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="A report")
        self.service = ReportAssignmentService(team=self.team, report_id=str(self.report.id))
        self.actor = ArtefactAttribution.from_user(self.user.id)
        self.member = User.objects.create(email="reviewer@example.com")
        OrganizationMembership.objects.create(user=self.member, organization=self.organization)
        self.reviewers = (SuggestedReviewerEntry(user_uuid=str(self.member.uuid)),)

    def proposal(
        self, *, outcome: Literal["selected", "no_suitable_owner", "lookup_failed"] = "selected"
    ) -> AssignmentProposal:
        return AssignmentProposal(
            operation_id=uuid4(),
            expected_state=self.service.read().state,
            source="research",
            reviewers=self.reviewers if outcome == "selected" else (),
            outcome=outcome,
            retry_reason="Member lookup unavailable" if outcome == "lookup_failed" else None,
        )

    def test_legacy_human_choice_survives_human_scout_human_sequence(self) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=list(self.reviewers)),
            attribution=self.actor,
            reevaluate_autostart=False,
        )
        chosen = SuggestedReviewers(root=[*self.reviewers, SuggestedReviewerEntry(user_uuid=str(self.user.uuid))])
        self.service.edit_reviewers(chosen, actor=self.actor)
        scout = self.proposal().model_copy(update={"reviewers": ()})
        assert not set_scout_report_reviewers(
            team_id=self.team.id,
            report_id=str(self.report.id),
            suggested_reviewers=SuggestedReviewers(root=[]),
            attribution=ArtefactAttribution.system(),
            proposal=scout,
        )
        assert self.service.read().reviewers == tuple(chosen.root)
        self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor, removal=True)
        assert self.service.read().control == "human"
        assert not self.service.read().reviewers
        assert not list(
            report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(self.member.uuid)],
                github_logins=[],
                logins_match_unidentified_only=True,
            )
        )

    @parameterized.expand([False, True])
    def test_automatic_first_migration_recovers_human_control(self, automatic_control: bool) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[]),
            attribution=self.actor,
            reevaluate_autostart=False,
        )
        if automatic_control:
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=ReviewerControl(mode="automatic"),
                attribution=ArtefactAttribution.system(),
                assignment_writer=True,
            )
        self.service.apply(self.proposal(), actor=ArtefactAttribution.system())
        assert self.service.read().control == "human"
        assert self.service.read().reviewers == ()

    def test_in_flight_proposal_cannot_apply_after_human_edit(self) -> None:
        self.service.edit_reviewers(SuggestedReviewers(root=list(self.reviewers)), actor=self.actor)
        stale = self.proposal()
        self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
        with self.assertRaises(StaleAssignmentProposal):
            self.service.apply(stale, actor=ArtefactAttribution.system())

    @parameterized.expand(["selected", "lookup_failed", "no_suitable_owner"])
    def test_fresh_results_preserve_human_choice(
        self, outcome: Literal["selected", "no_suitable_owner", "lookup_failed"]
    ) -> None:
        self.service.edit_reviewers(SuggestedReviewers(root=list(self.reviewers)), actor=self.actor)
        proposal = self.proposal(outcome=outcome)
        if outcome == "selected":
            proposal = proposal.model_copy(
                update={"reviewers": (SuggestedReviewerEntry(user_uuid=str(self.user.uuid)),)}
            )
        self.service.apply(proposal, actor=ArtefactAttribution.system())
        assert self.service.read().control == "human"
        assert self.service.read().reviewers == self.reviewers

    def test_retries_and_unchanged_proposals_do_not_repeat_reviewer_writes_or_delivery(self) -> None:
        proposal = self.proposal()
        with self.captureOnCommitCallbacks(execute=False):
            first = self.service.apply(proposal, actor=ArtefactAttribution.system())
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            replay = self.service.apply(proposal, actor=ArtefactAttribution.system(), reevaluate_autostart=True)
            unchanged = self.service.apply(
                self.proposal(), actor=ArtefactAttribution.system(), reevaluate_autostart=True
            )
        assert replay.replayed
        assert not replay.changed and not unchanged.changed
        assert first.reviewers_artefact.id == replay.reviewers_artefact.id == unchanged.reviewers_artefact.id
        assert self.report.artefacts.filter(type="suggested_reviewers").count() == 1
        assert callbacks == []
        with self.assertRaises(AssignmentOperationConflict):
            self.service.apply(
                proposal.model_copy(update={"source": "another-source"}), actor=ArtefactAttribution.system()
            )
        with self.assertRaises(ArtefactContentValidationError):
            first.reviewers_artefact.update_content([])

    def test_access_loss_cleans_legacy_recipient_without_releasing_human_control(self) -> None:
        UserSocialAuth.objects.create(
            user=self.member, provider="github", uid="1234", extra_data={"login": "example-reviewer"}
        )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[SuggestedReviewerEntry(github_login="example-reviewer")]),
            attribution=self.actor,
            reevaluate_autostart=False,
        )
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        result = self.service.apply(self.proposal(), actor=ArtefactAttribution.system())
        assert self.service.read().control == "human"
        assert self.service.read().reviewers == ()
        assert self.service.read().human_editor_id == self.user.id
        assert result.decision is not None
        assert result.decision.ineligible_user_uuids == (str(self.member.uuid),)

    def test_human_confirmation_preserves_editor_without_repeating_the_reviewer_row(self) -> None:
        self.service.apply(self.proposal(), actor=ArtefactAttribution.system())
        self.service.edit_reviewers(SuggestedReviewers(root=list(self.reviewers)), actor=self.actor)
        assert self.service.read().control == "human"
        assert self.service.read().human_editor_id == self.user.id
        assert self.report.artefacts.filter(type="suggested_reviewers").count() == 1

        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.service.apply(
            self.proposal().model_copy(update={"action": "cleanup", "reviewers": ()}),
            actor=ArtefactAttribution.system(),
        )
        assert self.service.read().reviewers == ()
        assert self.service.read().control == "human"
        assert self.service.read().human_editor_id == self.user.id

    def test_unresolved_login_is_evidence_not_a_recipient(self) -> None:
        proposal = self.proposal().model_copy(
            update={"reviewers": (SuggestedReviewerEntry(github_login="unlinked-example"),)}
        )
        result = self.service.apply(proposal, actor=ArtefactAttribution.system())
        assert self.service.read().reviewers == ()
        assert result.decision is not None
        assert result.decision.unresolved_candidates[0].github_login == "unlinked-example"

    def test_state_and_index_choose_one_reviewer_list_when_timestamps_match(self) -> None:
        timestamp = timezone.now()
        for number, reviewer in [(1, self.user), (2, self.member)]:
            SignalReportArtefact.objects.create(
                id=UUID(int=number),
                team=self.team,
                report=self.report,
                type="suggested_reviewers",
                content=SuggestedReviewers(
                    root=[SuggestedReviewerEntry(user_uuid=str(reviewer.uuid))]
                ).model_dump_json(),
            )
        self.report.artefacts.update(created_at=timestamp)
        sync_suggested_reviewer_index(team_id=self.team.id, report_id=str(self.report.id))

        assert self.service.read().reviewers == self.reviewers
        assert not list(
            report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(self.user.uuid)],
                github_logins=[],
                logins_match_unidentified_only=True,
            )
        )
        assert list(
            report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(self.member.uuid)],
                github_logins=[],
                logins_match_unidentified_only=True,
            )
        ) == [{"report_id": self.report.id}]

    def test_rollback_stops_automatic_updates_and_keeps_human_edits(self) -> None:
        self.service.apply(self.proposal(), actor=ArtefactAttribution.system())
        with patch("products.signals.backend.assignment_service.assignment_writer_enabled", return_value=False):
            paused = ReportAssignmentService(team=self.team, report_id=str(self.report.id))
            result = paused.apply_compatibility_reviewers(
                SuggestedReviewers(root=[]), actor=ArtefactAttribution.system()
            )
            assert not result.changed
            paused.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
            assert paused.read().control == "human"
            assert paused.read().reviewers == ()
        with self.assertRaises(ArtefactContentValidationError):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=SuggestedReviewers(root=list(self.reviewers)),
                attribution=ArtefactAttribution.system(),
            )

    def test_human_cannot_add_a_member_without_project_access(self) -> None:
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        with self.assertRaisesMessage(AssignmentWriteError, "access to this project"):
            self.service.edit_reviewers(SuggestedReviewers(root=list(self.reviewers)), actor=self.actor)
        assert not self.report.assignment_revisions.exists()
        assert not self.report.artefacts.exists()

    def test_producer_must_supply_selection_time_state(self) -> None:
        with self.assertRaises(StaleAssignmentProposal):
            self.service.apply_compatibility_reviewers(
                SuggestedReviewers(root=list(self.reviewers)), actor=ArtefactAttribution.system()
            )
        assert not self.report.assignment_revisions.exists()

    def test_claim_is_checked_before_write_and_recorded_on_decision(self) -> None:
        claim = SignalReportArtefact.add_log(
            team_id=self.team.id, report_id=str(self.report.id), content=WorkClaim(), attribution=self.actor
        )
        proposal = self.proposal()
        with self.assertRaises(AssignmentClaimConflict):
            self.service.apply(proposal, actor=ArtefactAttribution.system(), claim_id=str(claim.id))
        result = self.service.apply(proposal, actor=self.actor, claim_id=str(claim.id))
        assert str(result.reviewers_artefact.claim_id) == str(claim.id)
        assert self.report.artefacts.get(type="assignment_decision").claim_id == claim.id

    @parameterized.expand([(False, False, False), (True, False, False), (True, True, False), (True, True, True)])
    def test_delivery_gates_survive_writer_rollback(self, versioned: bool, effects: bool, github: bool) -> None:
        if versioned:
            self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
        with (
            patch("products.signals.backend.assignment_flags.assignment_side_effects_enabled", return_value=effects),
            patch(
                "products.signals.backend.assignment_flags.assignment_github_application_enabled", return_value=github
            ),
        ):
            assert assignment_side_effects_allowed(team_id=self.team.id, report_id=str(self.report.id)) == (
                not versioned or effects
            )
            assert assignment_side_effects_allowed(
                team_id=self.team.id, report_id=str(self.report.id), github=True
            ) == (not versioned or (effects and github))


class TestAssignmentReleaseControls(SimpleTestCase):
    @parameterized.expand([(None, False), (False, False), ("enabled", False), (True, True)])
    def test_writer_requires_explicit_enablement(self, value: object, enabled: bool) -> None:
        with patch("products.signals.backend.assignment_flags.Team.objects") as teams:
            teams.values_list.return_value.get.return_value = "example-org"
            with patch("products.signals.backend.assignment_flags.feature_enabled_or_false", return_value=value):
                assert assignment_writer_enabled(1) is enabled
