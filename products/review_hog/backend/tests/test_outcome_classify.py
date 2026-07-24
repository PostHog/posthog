from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.models.team import Team

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    FindingOutcomeArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.outcomes.classify import (
    _ClassifiedOutcome,
    _gather_report_inputs,
    _load_persisted_outcomes,
    _mark_outcomes_emitted,
    _PublishedFinding,
    _ReportInputs,
    classify_report,
    classify_team,
)
from products.review_hog.backend.reviewer.outcomes.discovery import unclassified_published_reports
from products.signals.backend.artefact_attribution import ArtefactAttribution

_CLASSIFY = "products.review_hog.backend.reviewer.outcomes.classify"
# Touches the finding's line 10 → a line-proximity candidate the judge then rules on.
_TOUCHING = [{"filename": "f.py", "patch": "@@ -10,1 +10,1 @@\n-old\n+new\n"}]
# Changes only line 80 → nowhere near the finding at line 10.
_FAR = [{"filename": "f.py", "patch": "@@ -80,1 +80,1 @@\n-old\n+new\n"}]

_ISSUE_KEY = "r1:f.py:10:logic"


def _finding(
    issue_key: str = _ISSUE_KEY, title: str = "Off-by-one", priority: IssuePriority = IssuePriority.MUST_FIX
) -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=issue_key,
        run_index=1,
        title=title,
        file="f.py",
        lines=[LineRange(start=10)],
        body="loop runs one short",
        suggestion="use <=",
        priority=priority,
        source_perspective="logic",
    )


def _verdict(issue_key: str = _ISSUE_KEY) -> ValidationVerdict:
    return ValidationVerdict(issue_key=issue_key, is_valid=True, argumentation="real bug", category="bug")


class TestClassifyReportDecision:
    """The precedence + emit logic, with the DB helpers mocked so no database or thread is involved."""

    def _inputs(self, *, comment: dict[str, Any] | None, compare_files: list[dict[str, Any]]) -> _ReportInputs:
        return _ReportInputs(
            reviewed_head="base_sha",
            compare_files=compare_files,
            review_comments=[comment] if comment else [],
            published=[_PublishedFinding(finding=_finding(), verdict=_verdict(), comment=comment)],
            distinct_id="user-distinct",
            judge_user_id=0,
        )

    def _run(self, *, inputs: _ReportInputs, judge_return: bool = True, report: ReviewReport | None = None):
        report = report or ReviewReport(repository="o/r", pr_number=7)
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=inputs),
            patch(f"{_CLASSIFY}._persist_outcomes"),
            patch(f"{_CLASSIFY}._mark_outcomes_emitted"),
            patch(f"{_CLASSIFY}.judge_addressed", new=AsyncMock(return_value=judge_return)) as judge,
        ):
            async_to_sync(classify_report)(
                team_id=1, report=report, final_head="head_sha", capture=lambda **kw: captured.append(kw)
            )
        return captured, judge

    def test_reacted_takes_precedence_and_skips_the_judge(self):
        # A reaction settles the finding as `reacted` before we spend a judge call — even though the
        # diff also touched its lines. Precedence inversion here would waste tokens and mislabel.
        comment = {"id": 1, "path": "f.py", "body": "### Off-by-one\n\nbody", "reactions": {"total_count": 1}}
        captured, judge = self._run(inputs=self._inputs(comment=comment, compare_files=_TOUCHING))
        judge.assert_not_awaited()
        assert captured[0]["properties"]["outcome"] == "reacted"
        assert captured[0]["properties"]["classification_method"] == "comment_reaction"

    def test_addressed_when_touched_and_judge_confirms(self):
        captured, judge = self._run(inputs=self._inputs(comment=None, compare_files=_TOUCHING), judge_return=True)
        judge.assert_awaited_once()
        assert captured[0]["properties"]["outcome"] == "addressed"
        assert captured[0]["properties"]["classification_method"] == "judge_confirmed"

    def test_ignored_when_touched_but_judge_rejects(self):
        captured, _judge = self._run(inputs=self._inputs(comment=None, compare_files=_TOUCHING), judge_return=False)
        assert captured[0]["properties"]["outcome"] == "ignored"
        assert captured[0]["properties"]["classification_method"] == "judge_rejected"

    def test_ignored_when_untouched_skips_the_judge(self):
        captured, judge = self._run(inputs=self._inputs(comment=None, compare_files=_FAR))
        judge.assert_not_awaited()
        assert captured[0]["properties"]["outcome"] == "ignored"
        assert captured[0]["properties"]["classification_method"] == "no_signal"

    def test_event_uuid_is_deterministic_per_finding(self):
        # The uuid is the consumer-side dedup key: ClickHouse never collapses duplicate uuids (the
        # events table's sort key includes the ingestion timestamp), so a crash-window re-emit is only
        # harmless because consumers can aggregate per distinct uuid. Switching to uuid4/a timestamp
        # would make crash-window duplicates indistinguishable from real events.
        report = ReviewReport(repository="o/r", pr_number=7)
        first, _ = self._run(inputs=self._inputs(comment=None, compare_files=_FAR), report=report)
        second, _ = self._run(inputs=self._inputs(comment=None, compare_files=_FAR), report=report)
        assert first[0]["uuid"] == second[0]["uuid"]

    def test_failure_mid_report_persists_and_emits_nothing(self):
        # A judge death partway must leave no trace on either side: a partial artefact write would
        # strand the report's remaining findings, and any event emitted before the outcomes are
        # durably decided could conflict with what a retry re-decides (a human reply landing in the
        # gap flips `ignored` to `reacted`) — the double-row corruption the persist-first order
        # exists to prevent.
        published = [
            _PublishedFinding(finding=_finding(), verdict=_verdict(), comment=None),
            _PublishedFinding(
                finding=_finding(issue_key="r1:f.py:11:logic", title="Two"), verdict=_verdict(), comment=None
            ),
        ]
        inputs = _ReportInputs(
            reviewed_head="base_sha",
            compare_files=_TOUCHING,
            review_comments=[],
            published=published,
            distinct_id="user-distinct",
            judge_user_id=0,
        )
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=inputs),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted") as mark,
            patch(f"{_CLASSIFY}.judge_addressed", new=AsyncMock(side_effect=[True, RuntimeError("judge died")])),
            pytest.raises(RuntimeError),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: captured.append(kw),
            )
        persist.assert_not_called()
        mark.assert_not_called()
        assert captured == []

    def test_no_events_emitted_when_persist_fails(self):
        # Guards the persist-before-emit order itself: if emission ever moves back ahead of the
        # durable write, a crash between the two re-decides outcomes on retry and ships conflicting
        # rows for the same finding.
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._inputs(comment=None, compare_files=_FAR)),
            patch(f"{_CLASSIFY}._persist_outcomes", side_effect=RuntimeError("db died")),
            patch(f"{_CLASSIFY}._mark_outcomes_emitted") as mark,
            pytest.raises(RuntimeError),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: captured.append(kw),
            )
        assert captured == []
        mark.assert_not_called()

    def test_resume_emits_stored_outcomes_flushes_then_marks(self):
        # The crash-recovery path: outcomes were persisted but the emitted stamp never landed. The
        # sweep must re-emit exactly what is stored — recomputing here could flip an outcome (a reply
        # arriving between attempts) and ship a conflicting duplicate — and must not spend GitHub,
        # judge, or warehouse work. The stamp may only land after flush(), else a hard kill between
        # the two silently loses the buffered events while the report reads as done.
        report = ReviewReport(repository="o/r", pr_number=7)
        stored = _ClassifiedOutcome(
            finding=_finding(),
            verdict=_verdict(),
            outcome="reacted",
            method="comment_reply",
            reviewed_head="base_sha",
            final_head="head_sha",
        )
        captured: list[dict[str, Any]] = []
        order: list[str] = []
        with (
            patch(f"{_CLASSIFY}.unclassified_published_reports", return_value=[report]),
            patch(f"{_CLASSIFY}._report_ids_with_persisted_outcomes", return_value={str(report.id)}),
            patch(f"{_CLASSIFY}._load_persisted_outcomes", return_value=([stored], "user-distinct")),
            patch(f"{_CLASSIFY}._mark_outcomes_emitted", side_effect=lambda **kw: order.append("mark")),
            patch(f"{_CLASSIFY}._gather_report_inputs", side_effect=AssertionError("resume must not refetch GitHub")),
            patch(
                f"{_CLASSIFY}.list_recently_merged_pull_requests",
                side_effect=AssertionError("resume must not need the warehouse"),
            ),
        ):
            classified = async_to_sync(classify_team)(
                team=Team(id=1),
                since=timezone.now(),
                capture=lambda **kw: captured.append(kw),
                flush=lambda: order.append("flush"),
            )
        assert classified == 1
        assert captured[0]["properties"]["outcome"] == "reacted"
        assert captured[0]["properties"]["classification_method"] == "comment_reply"
        assert captured[0]["uuid"] == str(uuid5(NAMESPACE_URL, f"reviewhog_finding_outcome:{report.id}:{_ISSUE_KEY}"))
        assert order == ["flush", "mark"]

    def test_event_carries_join_keys_and_finding_metadata(self):
        captured, _judge = self._run(inputs=self._inputs(comment=None, compare_files=_FAR))
        event = captured[0]
        assert event["event"] == "reviewhog_finding_outcome"
        assert event["distinct_id"] == "user-distinct"
        props = event["properties"]
        assert props["repository"] == "o/r"  # repository + pr_number are the HogQL join keys to provenance
        assert props["pr_number"] == 7
        assert props["issue_key"] == _ISSUE_KEY
        assert props["priority"] == "must_fix"
        assert props["category"] == "bug"
        assert props["source_perspective"] == "logic"
        assert props["reviewed_head"] == "base_sha"
        assert props["final_head"] == "head_sha"


class TestGatherAndIdempotency(BaseTest):
    """`_gather_report_inputs` and the artefact idempotency guard, against a real DB, synchronously."""

    def _report(self) -> ReviewReport:
        report = ReviewReport.objects.for_team(self.team.id).create(
            team=self.team,
            repository="o/r",
            pr_number=7,
            pr_url="https://github.com/o/r/pull/7",
            head_branch="feat",
            base_branch="main",
            acting_user=self.user,
            published_head_sha="base_sha",
        )
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=_finding(),
            attribution=ArtefactAttribution.system(),
        )
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=_verdict(),
            attribution=ArtefactAttribution.system(),
        )
        return report

    def test_gather_selects_published_finding_pairs_its_comment_and_resolves_distinct_id(self):
        report = self._report()
        comment = {"id": 1, "path": "f.py", "body": "### Off-by-one\n\nbody", "reactions": {"total_count": 0}}
        with (
            patch(f"{_CLASSIFY}._installation_auth", return_value=("tok", "inst")),
            patch(f"{_CLASSIFY}.fetch_compare_files", return_value=_FAR),
            patch(f"{_CLASSIFY}.fetch_review_comments", return_value=[comment]),
        ):
            inputs = _gather_report_inputs(team_id=self.team.id, report=report, final_head="head_sha")

        assert inputs.reviewed_head == "base_sha"
        assert [pf.finding.issue_key for pf in inputs.published] == [_ISSUE_KEY]
        assert inputs.published[0].comment == comment  # the finding was paired with its posted comment
        assert inputs.distinct_id == self.user.distinct_id

    def test_published_set_uses_the_threshold_snapshotted_at_publish(self):
        # The user's live threshold can change between publish and the merge sweep; the classifier
        # must reconstruct the published set from the snapshot taken when the review was posted
        # (here must_fix), not from current settings (default consider, which would admit both).
        report = self._report()
        report.published_urgency_threshold = IssuePriority.MUST_FIX.value
        report.save(update_fields=["published_urgency_threshold"])
        low = _finding(issue_key="r1:f.py:20:style", title="Nitpick", priority=IssuePriority.CONSIDER)
        ReviewReportArtefact.append_finding(
            team_id=self.team.id, report_id=str(report.id), content=low, attribution=ArtefactAttribution.system()
        )
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=_verdict(issue_key=low.issue_key),
            attribution=ArtefactAttribution.system(),
        )
        with (
            patch(f"{_CLASSIFY}._installation_auth", return_value=("tok", "inst")),
            patch(f"{_CLASSIFY}.fetch_compare_files", return_value=_FAR),
            patch(f"{_CLASSIFY}.fetch_review_comments", return_value=[]),
        ):
            inputs = _gather_report_inputs(team_id=self.team.id, report=report, final_head="head_sha")

        assert [pf.finding.issue_key for pf in inputs.published] == [_ISSUE_KEY]

    def test_discovery_tracks_the_emitted_stamp_not_artefact_presence(self):
        report = self._report()
        assert list(unclassified_published_reports(self.team.id)) == [report]

        ReviewReportArtefact.add_finding_outcome(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FindingOutcomeArtefact(
                issue_key=_ISSUE_KEY,
                run_index=1,
                outcome="ignored",
                method="no_signal",
                reviewed_head="base_sha",
                final_head="head_sha",
            ),
            attribution=ArtefactAttribution.system(),
        )

        # Artefacts mean "decided", not "delivered": a report that crashed between persist and the
        # emitted stamp must stay discoverable, or its events are silently lost forever.
        assert list(unclassified_published_reports(self.team.id)) == [report]
        # And the durable record round-trips as its typed content.
        artefact = ReviewReportArtefact.objects.for_team(self.team.id).get(
            report_id=str(report.id), type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME
        )
        parsed = parse_artefact_content(artefact.type, artefact.content)
        assert isinstance(parsed, FindingOutcomeArtefact)
        assert (parsed.outcome, parsed.method) == ("ignored", "no_signal")

        _mark_outcomes_emitted(team_id=self.team.id, report_id=str(report.id))
        assert unclassified_published_reports(self.team.id) == []

    def test_resume_rebuilds_stored_outcomes_verbatim(self):
        # `_load_persisted_outcomes` must reproduce exactly what the interrupted attempt decided —
        # outcome, method, and the heads it compared — from the durable rows alone. Any re-derivation
        # here (or a bad join back to the finding/verdict) would make the crash-window re-emit differ
        # from the original event.
        report = self._report()
        ReviewReportArtefact.add_finding_outcome(
            team_id=self.team.id,
            report_id=str(report.id),
            content=FindingOutcomeArtefact(
                issue_key=_ISSUE_KEY,
                run_index=1,
                outcome="reacted",
                method="comment_reply",
                reviewed_head="base_sha",
                final_head="head_sha",
            ),
            attribution=ArtefactAttribution.system(),
        )

        outcomes, distinct_id = _load_persisted_outcomes(team_id=self.team.id, report=report)

        assert distinct_id == self.user.distinct_id
        [outcome] = outcomes
        assert (outcome.outcome, outcome.method) == ("reacted", "comment_reply")
        assert (outcome.reviewed_head, outcome.final_head) == ("base_sha", "head_sha")
        assert outcome.finding.issue_key == _ISSUE_KEY
        assert outcome.verdict.category == "bug"
