from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    ReviewerEdit,
    ReviewerProposal,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    WorkClaim,
)
from products.signals.backend.assignment_flags import assignment_side_effects_allowed, assignment_writer_enabled
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.reviewer_rules import ReviewerRules, ReviewerWriteError, StaleReviewerProposal
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers, sync_suggested_reviewer_index


class TestReviewerRules(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        effects = patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=False)
        effects.start()
        self.addCleanup(effects.stop)
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="A report")
        self.rules = ReviewerRules(team=self.team, report_id=str(self.report.id))
        self.actor = ArtefactAttribution.from_user(self.user.id)
        self.member = User.objects.create(email="reviewer@example.com")
        OrganizationMembership.objects.create(user=self.member, organization=self.organization)
        self.me = SuggestedReviewerEntry(user_uuid=str(self.user.uuid))
        self.other = SuggestedReviewerEntry(user_uuid=str(self.member.uuid))

    def write(
        self,
        *reviewers: SuggestedReviewerEntry,
        edit: ReviewerEdit | None = None,
        proposal: ReviewerProposal | None = None,
    ) -> SignalReportArtefact:
        return SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=list(reviewers)),
            attribution=self.actor if edit else ArtefactAttribution.system(),
            reviewer_edit=edit,
            reviewer_proposal=proposal or ReviewerProposal(expected_state=self.rules.read().state),
        )

    def test_self_removal_allows_a_new_owner_without_restoring_the_editor(self) -> None:
        self.write(self.me)
        self.write(self.me, edit=ReviewerEdit(action="remove"))
        self.write(self.me, self.other)
        snapshot = self.rules.read()
        assert snapshot.reviewers == (self.other,)
        assert snapshot.corrections.excluded == (self.me,)
        assert not snapshot.corrections.confirmed
        assert (
            list(
                report_ids_naming_reviewers(
                    team_id=self.team.id,
                    user_uuids=[str(self.user.uuid)],
                    github_logins=[],
                    logins_match_unidentified_only=True,
                )
            )
            == []
        )

    def test_login_only_removal_survives_identity_change(self) -> None:
        UserSocialAuth.objects.create(
            user=self.member, provider="github", uid="renamed-reviewer", extra_data={"login": "previous-login"}
        )
        self.write(self.other)
        self.write(SuggestedReviewerEntry(github_login="previous-login"), edit=ReviewerEdit(action="remove"))
        assert self.rules.read().corrections.excluded[0].user_uuid == str(self.member.uuid)
        self.member.social_auth.filter(provider="github").update(extra_data={"login": "current-login"})
        self.write(SuggestedReviewerEntry(user_uuid=str(self.member.uuid), github_login="current-login"))
        assert self.rules.read().reviewers == ()

    def test_pin_preserves_only_the_person_added_and_a_later_removal_reverses_it(self) -> None:
        self.write(self.other)
        self.write(self.me, edit=ReviewerEdit(action="add"))
        self.write()
        assert self.rules.read().reviewers == (self.me,)
        self.write(self.me, edit=ReviewerEdit(action="remove"))
        self.write(self.me, self.other)
        assert self.rules.read().reviewers == (self.other,)
        self.write(self.me, edit=ReviewerEdit(action="add"))
        assert self.rules.read().corrections.excluded == ()
        assert self.rules.read().corrections.pinned == (self.me,)

    def test_pin_changes_the_state_token_without_repeating_the_list(self) -> None:
        first = self.write(self.me)
        stale = ReviewerProposal(expected_state=self.rules.read().state)
        pinned = self.write(self.me, edit=ReviewerEdit(action="add"))
        assert pinned.id == first.id
        with self.assertRaises(StaleReviewerProposal):
            self.write(self.other, proposal=stale)
        assert self.rules.read().reviewers == (self.me,)

    @parameterized.expand([False, True])
    def test_confirmation_protects_the_whole_list_including_empty(self, empty: bool) -> None:
        self.write(*(() if empty else (self.me,)))
        self.write(edit=ReviewerEdit(action="confirm", expected_state=self.rules.read().state))
        self.write(self.other)
        assert self.rules.read().reviewers == (() if empty else (self.me,))
        self.write(self.other, edit=ReviewerEdit(action="add"))
        self.write()
        assert self.rules.read().reviewers == ((self.other,) if empty else (self.me, self.other))
        assert self.rules.read().corrections.confirmed

    @parameterized.expand(["replace", "confirm"])
    def test_stale_full_list_operations_do_not_discard_new_people(self, action: str) -> None:
        self.write(self.me)
        stale = self.rules.read().state
        self.write(self.other, edit=ReviewerEdit(action="add"))
        with self.assertRaises(StaleReviewerProposal):
            self.write(self.me, edit=ReviewerEdit(action=action, expected_state=stale))
        assert self.rules.read().reviewers == (self.me, self.other)

    def test_independent_human_operations_merge_against_current_membership(self) -> None:
        self.write(self.me)
        stale = self.rules.read().state
        self.write(self.other, edit=ReviewerEdit(action="add", expected_state=stale))
        self.write(self.me, edit=ReviewerEdit(action="remove", expected_state=stale))
        assert self.rules.read().reviewers == (self.other,)

    @parameterized.expand(["lookup_failed", "invalid"])
    def test_failed_selection_keeps_valid_recipients(self, outcome: str) -> None:
        self.write(self.me)
        if outcome == "invalid":
            self.write(SuggestedReviewerEntry(github_login="unknown-example"))
        else:
            self.write(
                proposal=ReviewerProposal(
                    expected_state=self.rules.read().state,
                    outcome="lookup_failed",
                    retry_reason="Member lookup unavailable",
                )
            )
        assert self.rules.read().reviewers == (self.me,)

    def test_no_owner_clears_automatic_people_but_preserves_pins(self) -> None:
        self.write(self.other)
        self.write(self.me, edit=ReviewerEdit(action="add"))
        self.write(proposal=ReviewerProposal(expected_state=self.rules.read().state, outcome="no_suitable_owner"))
        assert self.rules.read().reviewers == (self.me,)

    def test_access_checks_override_a_pin_and_confirmation(self) -> None:
        self.write(self.other, edit=ReviewerEdit(action="add"))
        self.write(edit=ReviewerEdit(action="confirm", expected_state=self.rules.read().state))
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.write(self.me)
        assert self.rules.read().reviewers == ()
        assert self.rules.read().corrections.confirmed
        with self.assertRaises(ReviewerWriteError):
            self.write(self.other, edit=ReviewerEdit(action="add"))

    def test_unchanged_write_creates_no_rows_or_delivery_and_stale_retry_conflicts(self) -> None:
        proposal = ReviewerProposal(expected_state=self.rules.read().state)
        first = self.write(self.me, proposal=proposal)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            same = self.write(self.me)
        assert callbacks == []
        assert same.id == first.id
        assert self.report.artefacts.count() == 2
        with self.assertRaises(StaleReviewerProposal):
            self.write(self.me, proposal=proposal)
        with self.assertRaises(ArtefactContentValidationError):
            first.update_content([])

    def test_rollback_keeps_corrections_and_does_not_enable_delivery(self) -> None:
        self.write(self.me)
        with (
            patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=False),
            patch("products.signals.backend.assignment_flags.assignment_side_effects_enabled", return_value=False),
            self.captureOnCommitCallbacks(execute=False) as callbacks,
        ):
            self.write(self.other)
            assert self.rules.read().reviewers == (self.me,)
            self.write(proposal=ReviewerProposal(expected_state=self.rules.read().state, outcome="no_suitable_owner"))
            assert self.rules.read().reviewers == (self.me,)
            self.write(self.me, edit=ReviewerEdit(action="remove"))
            assert self.rules.read().reviewers == ()
            assert not assignment_side_effects_allowed(team_id=self.team.id, report_id=str(self.report.id))
        assert callbacks == []

    @parameterized.expand([False, True])
    def test_legacy_deltas_protect_only_edits_and_missing_evidence_pauses_automation(self, logged: bool) -> None:
        with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=False):
            self.write(self.me, self.other)
            self.write(self.me, edit=ReviewerEdit(action="remove"))
        if logged:
            ActivityLog.objects.create(
                team_id=self.team.id,
                user=self.user,
                scope="SignalReport",
                item_id=str(self.report.id),
                activity="suggested_reviewers_changed",
                detail={
                    "changes": [
                        {
                            "field": "suggested_reviewers",
                            "before": [str(self.user.uuid), str(self.member.uuid)],
                            "after": [str(self.member.uuid)],
                        }
                    ]
                },
            )
        pending = self.rules.read()
        assert pending.corrections.needs_review
        assert pending.state.corrections_id is None
        assert self.report.artefacts.count() == 2
        with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=False):
            self.write(self.me, proposal=ReviewerProposal(expected_state=pending.state, source="research"))
        assert self.rules.read().reviewers == (self.other,)
        assert self.report.artefacts.count() == 2
        self.write(self.me)
        snapshot = self.rules.read()
        assert snapshot.reviewers == (() if logged else (self.other,))
        assert snapshot.corrections.needs_review is not logged
        assert not snapshot.corrections.confirmed
        assert not snapshot.corrections.pinned
        ActivityLog.objects.filter(team_id=self.team.id, item_id=str(self.report.id)).delete()
        self.write(self.me)
        assert self.rules.read() == snapshot
        assert self.report.artefacts.filter(type="reviewer_corrections").count() == 1

    def test_unresolved_legacy_identity_requires_review(self) -> None:
        with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=False):
            self.write(SuggestedReviewerEntry(github_login="former-login"))
            self.write(edit=ReviewerEdit(action="replace"))
        ActivityLog.objects.create(
            team_id=self.team.id,
            user=self.user,
            scope="SignalReport",
            item_id=str(self.report.id),
            activity="suggested_reviewers_changed",
            detail={"changes": [{"field": "suggested_reviewers", "before": ["former-login"], "after": []}]},
        )
        self.write(self.other)
        snapshot = self.rules.read()
        assert snapshot.reviewers == ()
        assert snapshot.corrections.needs_review

    def test_login_exclusion_still_applies_after_member_resolution(self) -> None:
        UserSocialAuth.objects.create(
            user=self.member, provider="github", uid="1234", extra_data={"login": "example-reviewer"}
        )
        self.write(self.other)
        self.write(SuggestedReviewerEntry(github_login="example-reviewer"), edit=ReviewerEdit(action="remove"))
        self.write(self.other)
        assert self.rules.read().reviewers == ()

    def test_claim_must_belong_to_the_writer(self) -> None:
        claim = SignalReportArtefact.add_log(
            team_id=self.team.id, report_id=str(self.report.id), content=WorkClaim(), attribution=self.actor
        )
        with self.assertRaises(ArtefactContentValidationError):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=SuggestedReviewers(root=[self.me]),
                attribution=ArtefactAttribution.system(),
                reviewer_proposal=ReviewerProposal(expected_state=self.rules.read().state),
                claim_id=str(claim.id),
            )
        assert not self.report.artefacts.filter(type="suggested_reviewers").exists()

    def test_state_and_index_choose_the_same_list_when_timestamps_match(self) -> None:
        for number, reviewer in [(1, self.me), (2, self.other)]:
            SignalReportArtefact.objects.create(
                id=UUID(int=number),
                team=self.team,
                report=self.report,
                type="suggested_reviewers",
                content=SuggestedReviewers(root=[reviewer]).model_dump_json(),
            )
        self.report.artefacts.update(created_at=timezone.now())
        sync_suggested_reviewer_index(team_id=self.team.id, report_id=str(self.report.id))
        assert self.rules.read().reviewers == (self.other,)
        assert list(
            report_ids_naming_reviewers(
                team_id=self.team.id,
                user_uuids=[str(self.member.uuid)],
                github_logins=[],
                logins_match_unidentified_only=True,
            )
        ) == [{"report_id": self.report.id}]


class TestAssignmentReleaseControls(SimpleTestCase):
    @parameterized.expand([(None, False), (False, False), ("enabled", False), (True, True)])
    def test_writer_requires_explicit_enablement(self, value: object, enabled: bool) -> None:
        with patch("products.signals.backend.assignment_flags.Team.objects") as teams:
            teams.values_list.return_value.get.return_value = "example-org"
            with patch(
                "products.signals.backend.assignment_flags.feature_enabled_or_false", return_value=value
            ) as flag:
                assert assignment_writer_enabled(1) is enabled
                assert flag.call_args.kwargs["only_evaluate_locally"] is True
