import json
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
    RelevantCommit,
    ReviewerEdit,
    ReviewerProposal,
    ReviewerState,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    WorkClaim,
)
from products.signals.backend.assignment_flags import assignment_side_effects_allowed, assignment_writer_enabled
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)
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

    @parameterized.expand([(False, False), (True, False), (True, True)])
    def test_automatic_writes_load_each_members_identity_once(self, pinned: bool, selected: bool) -> None:
        self.write(self.me)
        if pinned:
            self.write(self.other, edit=ReviewerEdit(action="add"))
        candidates = (self.me, self.other) if selected else (self.me,)
        expected = (self.me, self.other) if pinned else (self.me,)
        for _ in range(2):
            with patch(
                "products.signals.backend.reviewer_rules.get_org_member_github_logins_by_user_uuid",
                wraps=get_org_member_github_logins_by_user_uuid,
            ) as lookup:
                self.write(*candidates)
            assert sorted(user_uuid for call in lookup.call_args_list for user_uuid in call.args[1]) == sorted(
                entry.user_uuid for entry in expected if entry.user_uuid
            )
            assert self.rules.read().reviewers == expected

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

    @parameterized.expand([False, True])
    def test_unchanged_write_creates_no_rows_or_delivery_and_stale_retry_conflicts(self, wording: bool) -> None:
        reviewer = SuggestedReviewerEntry(
            user_uuid=self.me.user_uuid,
            relevant_commits=[RelevantCommit(sha="abcdef0", reason="Fix", url="https://example.com/commit")],
        )
        proposal = ReviewerProposal(expected_state=self.rules.read().state, source="research")
        first = self.write(reviewer, proposal=proposal)
        proposed = reviewer.model_copy(deep=True)
        if wording:
            proposed.reason = "A new explanation for the same selection."
            proposed.github_name = "Reviewer name"
            proposed.relevant_commits[0].reason = "A new explanation for the same commit."
        with (
            patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=True),
            self.captureOnCommitCallbacks(execute=False) as callbacks,
        ):
            same = self.write(
                proposed, proposal=ReviewerProposal(expected_state=self.rules.read().state, source="research")
            )
        assert callbacks == []
        assert same.id == first.id
        assert self.report.artefacts.count() == 2
        with self.assertRaises(StaleReviewerProposal):
            self.write(proposed, proposal=proposal)
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

    def test_legacy_recovery_resolves_all_logins_once(self) -> None:
        for user, login in [(self.user, "first-reviewer"), (self.member, "second-reviewer")]:
            UserSocialAuth.objects.create(user=user, provider="github", uid=login, extra_data={"login": login})
        lists = [[], ["first-reviewer"], ["first-reviewer", "second-reviewer"], ["second-reviewer"], []]
        for before, after in zip(lists, lists[1:]):
            SignalReportArtefact.objects.create(
                team=self.team,
                report=self.report,
                type="suggested_reviewers",
                actor_kind="user",
                created_by=self.user,
                content=json.dumps([{"github_login": login} for login in after]),
            )
            ActivityLog.objects.create(
                team_id=self.team.id,
                user=self.user,
                scope="SignalReport",
                item_id=str(self.report.id),
                activity="suggested_reviewers_changed",
                detail={"changes": [{"field": "suggested_reviewers", "before": before, "after": after}]},
            )
        with patch(
            "products.signals.backend.reviewer_rules.resolve_org_github_login_to_users",
            wraps=resolve_org_github_login_to_users,
        ) as resolve:
            corrections = self.rules._legacy_corrections(team_id=self.team.id, report_id=str(self.report.id))
        resolve.assert_called_once_with(self.team.id, {"first-reviewer", "second-reviewer"})
        assert not corrections.needs_review
        assert not corrections.pinned
        assert {entry.user_uuid for entry in corrections.excluded} == {str(self.user.uuid), str(self.member.uuid)}

    @parameterized.expand([None, "old-format"])
    def test_legacy_commit_evidence_is_normalized(self, commits: object) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type="suggested_reviewers",
            content=json.dumps([{"user_uuid": str(self.user.uuid), "relevant_commits": commits}]),
        )
        assert self.rules.read().reviewers == (self.me,)
        self.write(self.other)
        assert self.rules.read().reviewers == (self.other,)

    @parameterized.expand(["{", "{}", '[{"github_login": "valid-reviewer"}, {}]'])
    def test_invalid_legacy_reviewers_do_not_look_like_an_empty_assignment(self, content: str) -> None:
        row = SignalReportArtefact.objects.create(
            team=self.team, report=self.report, type="suggested_reviewers", content=content
        )
        snapshot = self.rules.read()
        assert snapshot.invalid_reviewers
        assert snapshot.corrections.needs_review
        for enabled in (False, True):
            with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=enabled):
                with self.assertRaises(ReviewerWriteError):
                    self.write(self.other)
                for action in ("add", "remove", "confirm"):
                    with self.assertRaises(ReviewerWriteError):
                        self.write(self.other, edit=ReviewerEdit(action=action, expected_state=snapshot.state))
                for expected in (None, ReviewerState()):
                    with self.assertRaises(StaleReviewerProposal):
                        self.write(self.other, edit=ReviewerEdit(action="replace", expected_state=expected))
                with self.assertRaises(ReviewerWriteError):
                    self.write(
                        SuggestedReviewerEntry(github_login="unknown-example"),
                        edit=ReviewerEdit(action="replace", expected_state=snapshot.state),
                    )
                with self.assertRaises(ReviewerWriteError):
                    SignalReportArtefact.append_status(
                        team_id=self.team.id,
                        report_id=str(self.report.id),
                        content=SuggestedReviewers(root=[self.other]),
                        attribution=ArtefactAttribution.system(),
                        reviewer_edit=ReviewerEdit(action="replace", expected_state=snapshot.state),
                    )
        row.refresh_from_db()
        assert row.content == content
        assert self.report.artefacts.count() == 1

    @parameterized.expand([(False, False), (False, True), (True, False), (True, True)])
    def test_human_repair_preserves_corrections_and_history(self, enabled: bool, empty: bool) -> None:
        self.write(self.me, self.other)
        self.write(self.me, edit=ReviewerEdit(action="remove"))
        self.write(self.other, edit=ReviewerEdit(action="add"))
        row = SignalReportArtefact.objects.create(
            team=self.team, report=self.report, type="suggested_reviewers", content="{"
        )
        snapshot = self.rules.read()
        replacement = () if empty else (self.other,)
        with patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=enabled):
            self.write(*replacement, edit=ReviewerEdit(action="replace", expected_state=snapshot.state))
            repaired = self.rules.read()
            assert not repaired.invalid_reviewers
            assert repaired.reviewers == replacement
            assert repaired.corrections == snapshot.corrections
            assert repaired.corrections.needs_review
            assert not repaired.corrections.confirmed
            assert repaired.state.corrections_id != snapshot.state.corrections_id
            self.write(self.me, self.other)
            assert self.rules.read() == repaired
            self.write(edit=ReviewerEdit(action="confirm", expected_state=repaired.state))
            assert not self.rules.read().corrections.needs_review
        row.refresh_from_db()
        assert row.content == "{"

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
