import json
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models import OrganizationMembership, Team, User
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
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReviewerExclusion,
    SignalReviewerExclusionRevision,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)
from products.signals.backend.reviewer_exclusions import (
    DuplicateExclusion,
    StandingExclusions,
    create_exclusion,
    revise_exclusion,
    revoke_exclusion,
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


class TestStandingExclusions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enabled = True
        self.flag = patch(
            "products.signals.backend.reviewer_rules.assignment_writer_enabled", side_effect=lambda _: self.enabled
        )
        self.flag.start()
        self.addCleanup(self.flag.stop)
        effects = patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=False)
        effects.start()
        self.addCleanup(effects.stop)
        capture = patch("products.signals.backend.reviewer_rules.capture_reviewer_exclusion_applied")
        self.capture = capture.start()
        self.addCleanup(capture.stop)
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="A report")
        self.rules = ReviewerRules(team=self.team, report_id=str(self.report.id))
        self.member = User.objects.create(email="reviewer@example.com")
        OrganizationMembership.objects.create(user=self.member, organization=self.organization)
        self.me = SuggestedReviewerEntry(user_uuid=str(self.user.uuid))
        self.other = SuggestedReviewerEntry(user_uuid=str(self.member.uuid))
        SignalReportArtefact.objects.create(
            team=self.team, report=self.report, type="repo_selection", content=json.dumps({"repository": "Org/App"})
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type="signal_finding",
            content=json.dumps({"signal_id": "s1", "relevant_code_paths": ["/src/billing/charge.py"]}),
        )

    def exclude(self, **area: str) -> str:
        exclusion, _ = create_exclusion(
            team_id=self.team.id,
            actor_id=self.member.id,
            instruction="I moved off this area.",
            subject_user_uuid=self.member.uuid,
            **area,
        )
        return str(exclusion.id)

    def write(self, *reviewers: SuggestedReviewerEntry, source: str = "research") -> None:
        with self.captureOnCommitCallbacks(execute=True):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=SuggestedReviewers(root=list(reviewers)),
                attribution=ArtefactAttribution.system(),
                reviewer_proposal=ReviewerProposal(expected_state=self.rules.read().state, source=source),
            )

    @parameterized.expand(
        [
            ("research_any_repo", "research", {}, True, True, None, False),
            ("scout_same_repo", "scout", {"repository": "org/app"}, True, True, None, False),
            (
                "custom_agent_path",
                "custom_agent",
                {"repository": "org/app", "path_prefix": "src/billing"},
                True,
                True,
                None,
                False,
            ),
            ("other_repo", "research", {"repository": "org/other"}, True, False, None, False),
            ("other_path", "scout", {"repository": "org/app", "path_prefix": "src/bill"}, True, False, None, False),
            (
                "superseded_finding_path",
                "research",
                {"repository": "org/app", "path_prefix": "src/billing"},
                True,
                False,
                ["src/search/query.py"],
                False,
            ),
            ("writer_disabled", "research", {"repository": "org/app"}, False, True, None, False),
            ("writer_disabled_login_only", "custom_agent", {}, False, True, None, True),
        ]
    )
    def test_matching_instruction_suppresses_the_subject_for_every_writer(
        self,
        _name: str,
        source: str,
        area: dict[str, str],
        enabled: bool,
        suppressed: bool,
        rewritten_paths: list[str] | None,
        by_login: bool,
    ) -> None:
        self.enabled = enabled
        if rewritten_paths is not None:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=self.report,
                type="signal_finding",
                content=json.dumps({"signal_id": "s1", "relevant_code_paths": rewritten_paths}),
            )
        other = self.other
        if by_login:
            UserSocialAuth.objects.create(user=self.member, provider="github", uid="1", extra_data={"login": "member"})
            other = SuggestedReviewerEntry(github_login="member")
        exclusion_id = self.exclude(**area)
        self.write(self.me, other, source=source)
        assert [entry.user_uuid or entry.github_login for entry in self.rules.read().reviewers] == (
            [self.me.user_uuid] if suppressed else [self.me.user_uuid, other.user_uuid or other.github_login]
        )
        assert [call.kwargs for call in self.capture.call_args_list] == (
            [
                {
                    "team_id": self.team.id,
                    "report_id": str(self.report.id),
                    "source": source,
                    "events": [("suppressed", [exclusion_id])],
                }
            ]
            if suppressed
            else []
        )

    def test_unreadable_findings_do_not_block_a_path_instruction(self) -> None:
        for content in ["{not json", '{"signal_id": "s2", "relevant_code_paths": ["src/search/\\u0000.py"]}']:
            SignalReportArtefact.objects.create(
                team=self.team, report=self.report, type="signal_finding", content=content
            )
        self.exclude(repository="org/app", path_prefix="src/billing")
        self.write(self.me, self.other)
        assert [entry.user_uuid for entry in self.rules.read().reviewers] == [self.me.user_uuid]

    def test_login_only_writer_skips_identity_resolution_without_instructions(self) -> None:
        self.enabled = False
        UserSocialAuth.objects.create(user=self.member, provider="github", uid="1", extra_data={"login": "member"})
        with self.assertNumQueries(25):
            self.write(self.me, SuggestedReviewerEntry(github_login="member"), source="custom_agent")

    def test_revoked_instruction_stops_suppressing_and_keeps_history(self) -> None:
        exclusion_id = self.exclude()
        revise_exclusion(team_id=self.team.id, exclusion_id=exclusion_id, actor_id=self.user.id, repository="org/app")
        revise_exclusion(team_id=self.team.id, exclusion_id=exclusion_id, actor_id=self.user.id, repository=" Org/App ")
        revoke_exclusion(team_id=self.team.id, exclusion_id=exclusion_id, actor_id=self.user.id)
        self.write(self.other)
        assert [entry.user_uuid for entry in self.rules.read().reviewers] == [self.other.user_uuid]
        assert list(
            SignalReviewerExclusionRevision.objects.for_team(self.team.id)
            .filter(exclusion_id=exclusion_id)
            .order_by("revision")
            .values_list("revision", "action", "repository", "status", "actor_id")
        ) == [
            (1, "created", "", "active", self.member.id),
            (2, "revised", "org/app", "active", self.user.id),
            (3, "revoked", "org/app", "revoked", self.user.id),
        ]

    @parameterized.expand(
        [
            ("no_repository", {"repository": "org/app"}, "repo_selection", True),
            ("no_repository_writer_disabled", {"repository": "org/app"}, "repo_selection", False),
            ("no_paths", {"repository": "org/app", "path_prefix": "src"}, "signal_finding", True),
            ("no_paths_writer_disabled", {"repository": "org/app", "path_prefix": "src"}, "signal_finding", False),
        ]
    )
    def test_missing_area_state_keeps_the_current_selection(
        self, _name: str, area: dict[str, str], missing: str, enabled: bool
    ) -> None:
        self.enabled = enabled
        self.write(self.me)
        SignalReportArtefact.objects.filter(report=self.report, type=missing).delete()
        self.exclude(**area)
        self.write(self.other)
        assert [entry.user_uuid for entry in self.rules.read().reviewers] == [self.me.user_uuid]
        assert [event for call in self.capture.call_args_list for event in call.kwargs["events"]] == [
            ("unresolved", [])
        ]

    @parameterized.expand([("covered", True), ("repository_unknown", False)])
    def test_report_pin_wins_and_needs_a_person(self, _name: str, area_known: bool) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[self.other]),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reviewer_edit=ReviewerEdit(action="add"),
        )
        if not area_known:
            SignalReportArtefact.objects.filter(report=self.report, type="repo_selection").delete()
        exclusion_id = self.exclude(repository="org/app")
        self.write(self.me, self.other)
        snapshot = self.rules.read()
        assert [entry.user_uuid for entry in snapshot.reviewers] == (
            [self.me.user_uuid, self.other.user_uuid] if area_known else [self.other.user_uuid]
        )
        assert snapshot.corrections.needs_review is area_known
        assert [event for call in self.capture.call_args_list for event in call.kwargs["events"]] == [
            ("pin_conflict", [exclusion_id]) if area_known else ("unresolved", [])
        ]

    def test_confirmed_list_is_kept_without_reading_instructions(self) -> None:
        self.write(self.me)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers(root=[]),
            attribution=ArtefactAttribution.from_user(self.user.id),
            reviewer_edit=ReviewerEdit(action="confirm", expected_state=self.rules.read().state),
        )
        self.exclude()
        with CaptureQueriesContext(connection) as queries:
            self.write(self.other)
        assert [entry.user_uuid for entry in self.rules.read().reviewers] == [self.me.user_uuid]
        assert not [query for query in queries.captured_queries if "signalreviewerexclusion" in query["sql"]]

    def test_finding_paths_are_read_only_for_a_path_instruction_in_the_report_repository(self) -> None:
        self.exclude(repository="org/other", path_prefix="src/billing")
        self.exclude(repository="org/app")
        with CaptureQueriesContext(connection) as queries:
            StandingExclusions.load(team_id=self.team.id, report_id=str(self.report.id))
        assert not [query for query in queries.captured_queries if "signal_finding" in query["sql"]]

    def test_create_returns_the_active_twin_and_revise_rejects_one(self) -> None:
        first = self.exclude(repository="org/app")
        assert self.exclude(repository=" Org/App ") == first
        after_github_connect, created = create_exclusion(
            team_id=self.team.id,
            actor_id=self.member.id,
            instruction="I moved off this area.",
            subject_user_uuid=self.member.uuid,
            subject_github_login="Reviewer",
            repository="org/app",
        )
        assert (str(after_github_connect.id), created) == (first, False)
        second = self.exclude(repository="org/other")
        with self.assertRaises(DuplicateExclusion):
            revise_exclusion(team_id=self.team.id, exclusion_id=second, actor_id=self.user.id, repository="org/app")
        # A concurrent amend can pass the twin check and still lose the unique index.
        with (
            patch(
                "products.signals.backend.reviewer_exclusions._active_twins",
                return_value=SignalReviewerExclusion.objects.none(),
            ),
            self.assertRaises(DuplicateExclusion),
        ):
            revise_exclusion(team_id=self.team.id, exclusion_id=second, actor_id=self.user.id, repository="org/app")
        assert SignalReviewerExclusion.objects.for_team(self.team.id).get(id=second).repository == "org/other"

    def test_a_moved_login_does_not_make_another_member_a_twin(self) -> None:
        theirs, _ = create_exclusion(
            team_id=self.team.id,
            actor_id=self.member.id,
            instruction="Off.",
            subject_user_uuid=self.member.uuid,
            subject_github_login="shared-login",
        )
        mine, created = create_exclusion(
            team_id=self.team.id,
            actor_id=self.user.id,
            instruction="Off.",
            subject_user_uuid=self.user.uuid,
            subject_github_login="shared-login",
        )
        assert created
        assert {theirs.subject_user_uuid, mine.subject_user_uuid} == {self.member.uuid, self.user.uuid}

    def test_each_login_resolves_once_per_load(self) -> None:
        UserSocialAuth.objects.create(user=self.member, provider="github", uid="1", extra_data={"login": "member"})
        self.exclude()
        standing = StandingExclusions.load(team_id=self.team.id, report_id=str(self.report.id))
        with patch(
            "products.signals.backend.reviewer_exclusions.resolve_org_github_login_to_users",
            wraps=resolve_org_github_login_to_users,
        ) as resolve:
            assert standing.allowed_logins(["member", "someone"]) == ["someone"]
            assert standing.allowed_logins(["Member"]) == []
        assert resolve.call_count == 1

    def test_active_twin_is_scoped_to_one_team(self) -> None:
        self.exclude(repository="org/app")
        self.exclude(repository="org/other")
        other_team = Team.objects.create(organization=self.organization)
        same_area, created = create_exclusion(
            team_id=other_team.id,
            actor_id=self.member.id,
            instruction="I moved off this area.",
            subject_user_uuid=self.member.uuid,
            repository="org/app",
        )
        assert created
        revised = revise_exclusion(
            team_id=other_team.id, exclusion_id=same_area.id, actor_id=self.member.id, repository="org/other"
        )
        assert (revised.team_id, revised.repository) == (other_team.id, "org/other")


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
