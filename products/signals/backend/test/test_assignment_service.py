from typing import Literal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    AssignedPerson,
    AssignmentSelection,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    WorkClaim,
)
from products.signals.backend.assignment_flags import (
    assignment_agent_selection_enabled,
    assignment_github_application_enabled,
)
from products.signals.backend.assignment_service import (
    AssignmentOperationConflict,
    AssignmentProposal,
    AssignmentWriteError,
    ReportAssignmentService,
    StaleAssignmentProposal,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignmentRevision
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers


class TestReportAssignmentService(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="A report")
        self.service = ReportAssignmentService(team=self.team, report_id=str(self.report.id))
        self.actor = ArtefactAttribution.from_user(self.user.id)
        self.member = User.objects.create(email="assignment-member@example.com")
        OrganizationMembership.objects.create(user=self.member, organization=self.organization)
        self.selection = AssignmentSelection(people=(AssignedPerson(user_uuid=str(self.member.uuid)),))
        self.flag = patch(
            "products.signals.backend.assignment_service.assignment_agent_selection_enabled", return_value=True
        )
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def _proposal(
        self,
        *,
        selection: AssignmentSelection | None = None,
        outcome: Literal["selected", "no_suitable_owner", "lookup_failed"] = "selected",
    ) -> AssignmentProposal:
        snapshot = self.service.read()
        return AssignmentProposal(
            operation_id=uuid4(),
            expected_revision=snapshot.revision,
            evidence_revision=snapshot.evidence_revision,
            source="research",
            policy_version="1",
            selection=selection if selection is not None else self.selection,
            outcome=outcome,
            retry_reason="Member lookup unavailable" if outcome == "lookup_failed" else None,
        )

    def test_replay_returns_original_decision_without_writes_or_side_effects(self) -> None:
        proposal = self._proposal()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            first = self.service.apply(proposal, actor=ArtefactAttribution.system())
            with self.assertRaises(ArtefactContentValidationError):
                first.reviewers_artefact.update_content([])
            second = self.service.apply(proposal, actor=ArtefactAttribution.system())
        assert second.replayed
        assert first.decision == second.decision
        assert first.reviewers_artefact.id == second.reviewers_artefact.id
        assert [
            reviewer.model_dump()
            for reviewer in SuggestedReviewers.model_validate_json(second.reviewers_artefact.content).root
        ] == [person.model_dump() for person in first.decision.selection.people]
        assert self.report.assignment_revisions.count() == 1
        assert callbacks == []
        assert list(
            report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(self.member.uuid)],
                github_logins=[],
                logins_match_unidentified_only=True,
            )
        ) == [{"report_id": self.report.id}]

    def test_operation_id_cannot_be_reused_for_another_request(self) -> None:
        proposal = self._proposal()
        self.service.apply(proposal, actor=self.actor)
        with self.assertRaises(AssignmentOperationConflict):
            self.service.apply(proposal.model_copy(update={"policy_version": "2"}), actor=self.actor)
        assert self.service.read().selection == self.selection

    @parameterized.expand([("assignment",), ("evidence",)])
    def test_stale_proposal_cannot_overwrite_new_state(self, change: str) -> None:
        proposal = self._proposal()
        if change == "assignment":
            self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
        else:
            self.report.summary = "New findings"
            self.report.save(update_fields=["summary"])
        with self.assertRaises(StaleAssignmentProposal):
            self.service.apply(proposal, actor=ArtefactAttribution.system())
        assert self.service.read().selection.people == ()

    def test_human_additions_and_removals_survive_new_automatic_selection(self) -> None:
        self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        self.service.edit_reviewers(
            SuggestedReviewers(root=[SuggestedReviewerEntry(user_uuid=str(self.user.uuid))]), actor=self.actor
        )
        result = self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        assert [person.user_uuid for person in result.decision.selection.people] == [str(self.user.uuid)]
        assert result.decision.overrides.removed_user_uuids == (str(self.member.uuid),)

    def test_explicit_unassignment_survives_until_a_person_resumes_automatic_selection(self) -> None:
        self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
        result = self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        assert result.decision.selection.people == ()
        assert result.decision.overrides.unassigned
        resume = self._proposal(selection=AssignmentSelection()).model_copy(update={"action": "resume"})
        with self.assertRaises(AssignmentWriteError):
            self.service.apply(resume, actor=ArtefactAttribution.system())
        self.service.apply(resume, actor=self.actor)
        result = self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        assert result.decision.selection == self.selection

    @parameterized.expand([("selected", False), ("no_suitable_owner", False), ("lookup_failed", True)])
    def test_empty_selection_and_failed_lookup_have_different_effects(
        self, outcome: Literal["selected", "no_suitable_owner", "lookup_failed"], keeps_assignment: bool
    ) -> None:
        self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        result = self.service.apply(
            self._proposal(selection=AssignmentSelection(), outcome=outcome), actor=ArtefactAttribution.system()
        )
        assert bool(result.decision.selection.people) == keeps_assignment
        assert result.decision.requires_reassessment == keeps_assignment
        assert result.decision.outcome == outcome

    @parameterized.expand([("inactive",), ("left_organization",), ("project_access",)])
    def test_access_loss_removes_even_a_human_assignment(self, change: str) -> None:
        self.service.edit_reviewers(SuggestedReviewers(root=list(self.selection.people)), actor=self.actor)
        if change == "inactive":
            self.member.is_active = False
            self.member.save(update_fields=["is_active"])
        elif change == "left_organization":
            OrganizationMembership.objects.filter(user=self.member, organization=self.organization).delete()
        else:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
            self.team.organization = self.organization
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                access_level="none",
                organization_member=OrganizationMembership.objects.get(
                    user=self.member, organization=self.organization
                ),
            )
        result = self.service.apply(
            self._proposal(selection=AssignmentSelection(), outcome="lookup_failed"), actor=ArtefactAttribution.system()
        )
        assert result.decision.selection.people == ()
        assert result.decision.overrides.additions == ()
        assert result.decision.ineligible_user_uuids == (str(self.member.uuid),)
        assert result.decision.requires_reassessment
        assert SuggestedReviewers.model_validate_json(result.reviewers_artefact.content).root == []

    def test_new_ineligible_member_is_rejected_without_recording_a_decision(self) -> None:
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        with self.assertRaises(AssignmentWriteError):
            self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        assert self.report.assignment_revisions.count() == 0

    @parameterized.expand([(1,), (3,)])
    def test_member_resolution_scopes_access_and_batches_github_queries(self, member_count: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=OrganizationMembership.objects.get(user=self.member, organization=self.organization),
        )
        members = [self.member]
        for index in range(member_count - 1):
            member = User.objects.create(email=f"assignment-member-{index}@example.com")
            OrganizationMembership.objects.create(user=member, organization=self.organization)
            members.append(member)
        UserSocialAuth.objects.create(
            user=self.member, provider="github", uid="assignment-member", extra_data={"login": "example-reviewer"}
        )
        proposal = self._proposal(
            selection=AssignmentSelection(
                people=tuple(AssignedPerson(user_uuid=str(member.uuid)) for member in members)
            )
        )
        with CaptureQueriesContext(connection) as queries:
            result = self.service.apply(proposal, actor=ArtefactAttribution.system())

        assert [person.github_login for person in result.decision.selection.people] == ["example-reviewer"] + [None] * (
            member_count - 1
        )
        membership_queries = [
            query["sql"] for query in queries if 'FROM "posthog_organizationmembership"' in query["sql"]
        ]
        assert membership_queries
        assert all('"uuid"' in query.partition(" WHERE ")[2] for query in membership_queries)
        identity_tables = ("posthog_user_integration", "social_auth_usersocialauth", "posthog_integration")
        identity_queries = [
            query for query in queries if any(f'FROM "{table}"' in query["sql"] for table in identity_tables)
        ]
        assert len(identity_queries) == 3

    @parameterized.expand([("automatic",), ("human",)])
    def test_github_login_cannot_override_member_identity(self, source: str) -> None:
        selection = AssignmentSelection(
            people=(AssignedPerson(user_uuid=str(self.member.uuid), github_login="different-person"),)
        )
        if source == "automatic":
            reviewers = self.service.apply(
                self._proposal(selection=selection), actor=ArtefactAttribution.system()
            ).reviewers_artefact
        else:
            reviewers = self.service.edit_reviewers(SuggestedReviewers(root=list(selection.people)), actor=self.actor)
        assert self.service.read().selection.people[0].github_login is None
        assert SuggestedReviewers.model_validate_json(reviewers.content).root[0].github_login is None

    def test_legacy_login_suggestion_is_not_promoted_by_identity_enrichment(self) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[SuggestedReviewerEntry(github_login="example-reviewer")]),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )
        self.service.edit_reviewers(
            SuggestedReviewers(
                root=[SuggestedReviewerEntry(user_uuid=str(self.member.uuid), github_login="example-reviewer")]
            ),
            actor=self.actor,
        )
        snapshot = self.service.read()
        assert snapshot.selection.people == ()
        assert snapshot.overrides.additions == ()
        assert len(snapshot.selection.suggestions) == 1

    def test_assignment_does_not_change_an_active_claim(self) -> None:
        claim = SignalReportArtefact.add_log(
            team_id=self.team.id, report_id=str(self.report.id), content=WorkClaim(), attribution=self.actor
        )
        self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        active = get_active_claim(team_id=self.team.id, report_id=str(self.report.id))
        assert active is not None
        assert active.claim_id == claim.id

    def test_removing_a_legacy_login_keeps_the_removal_after_github_is_unlinked(self) -> None:
        identity = UserSocialAuth.objects.create(
            user=self.member, provider="github", uid="assignment-member", extra_data={"login": "example-reviewer"}
        )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[SuggestedReviewerEntry(github_login="example-reviewer")]),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )
        self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor, removal=True)
        identity.delete()
        result = self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
        assert result.decision.selection.people == ()
        assert result.decision.overrides.removed_user_uuids == (str(self.member.uuid),)
        assert not result.decision.overrides.unassigned

    def test_index_failure_rolls_back_decision_projection_and_callbacks(self) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with patch.object(SignalReportAssignmentRevision, "save", side_effect=RuntimeError("write failed")):
                with self.assertRaises(RuntimeError):
                    self.service.edit_reviewers(SuggestedReviewers(root=list(self.selection.people)), actor=self.actor)
        assert self.report.artefacts.count() == 0
        assert self.report.assignment_revisions.count() == 0
        assert callbacks == []

    def test_disabled_selection_still_allows_human_corrections(self) -> None:
        with patch(
            "products.signals.backend.assignment_service.assignment_agent_selection_enabled", return_value=False
        ):
            with self.assertRaises(AssignmentWriteError):
                self.service.apply(self._proposal(), actor=ArtefactAttribution.system())
            self.service.edit_reviewers(SuggestedReviewers(root=[]), actor=self.actor)
        assert self.service.read().overrides.unassigned


class TestAssignmentReleaseControls(SimpleTestCase):
    @parameterized.expand([(None, False), (False, False), ("enabled", False), (True, True)])
    @override_settings(DEBUG=True)
    def test_each_control_requires_explicit_enablement(self, value: object, enabled: bool) -> None:
        with patch("products.signals.backend.assignment_flags.Team.objects") as teams:
            teams.values_list.return_value.get.return_value = "example-org"
            with patch(
                "products.signals.backend.assignment_flags.feature_enabled_or_false", return_value=value
            ) as evaluate:
                assert assignment_agent_selection_enabled(1) is enabled
                assert assignment_github_application_enabled(1) is enabled
        assert [call.args[0] for call in evaluate.call_args_list] == [
            "signals-assignment-agent-selection",
            "signals-assignment-github-application",
        ]

    def test_unavailable_flag_service_disables_both_controls(self) -> None:
        with patch("products.signals.backend.assignment_flags.Team.objects") as teams:
            teams.values_list.return_value.get.return_value = "example-org"
            with patch("products.signals.backend.assignment_flags.feature_enabled_or_false", side_effect=RuntimeError):
                assert not assignment_agent_selection_enabled(1)
                assert not assignment_github_application_enabled(1)
