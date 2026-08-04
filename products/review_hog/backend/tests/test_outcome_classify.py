from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError

from posthog.models.team import Team

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    FindingOutcomeArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.constants import (
    OUTCOME_JUDGE_FAILURE_STREAK,
    OUTCOME_JUDGE_REASONING_MAX_CHARS,
    OUTCOME_MAX_JUDGE_CALLS_PER_REPORT,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.outcomes.classify import (
    _ClassifiedOutcome,
    _gather_report_inputs,
    _load_persisted_outcomes,
    _mark_outcomes_emitted,
    _PublishedFinding,
    _ReportInputs,
    _SkipReport,
    classify_report,
    classify_team,
)
from products.review_hog.backend.reviewer.outcomes.discovery import unclassified_published_reports
from products.review_hog.backend.reviewer.outcomes.judge import OutcomeJudgeVerdict
from products.signals.backend.artefact_attribution import ArtefactAttribution

_CLASSIFY = "products.review_hog.backend.reviewer.outcomes.classify"
# Touches the finding's line 10 → a line-proximity candidate the judge then rules on.
_TOUCHING = [{"filename": "f.py", "patch": "@@ -10,1 +10,1 @@\n-old\n+new\n"}]
# Changes only line 80 → nowhere near the finding at line 10.
_FAR = [{"filename": "f.py", "patch": "@@ -80,1 +80,1 @@\n-old\n+new\n"}]

_ISSUE_KEY = "r1:f.py:10:logic"


def _finding(
    issue_key: str = _ISSUE_KEY,
    title: str = "Off-by-one",
    priority: IssuePriority = IssuePriority.MUST_FIX,
    run_index: int = 1,
) -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=issue_key,
        run_index=run_index,
        title=title,
        file="f.py",
        lines=[LineRange(start=10)],
        body="loop runs one short",
        suggestion="use <=",
        priority=priority,
        source_perspective="logic",
    )


def _ruling(addressed: bool, reasoning: str = "the new guard covers the flagged path") -> OutcomeJudgeVerdict:
    return OutcomeJudgeVerdict(addressed=addressed, reasoning=reasoning)


def _verdict(issue_key: str = _ISSUE_KEY) -> ValidationVerdict:
    return ValidationVerdict(issue_key=issue_key, is_valid=True, argumentation="real bug", category="bug")


class TestClassifyReportDecision:
    """The precedence + emit logic, with the DB helpers mocked so no database or thread is involved."""

    def _inputs(self, *, comment: dict[str, Any] | None, compare_files: list[dict[str, Any]]) -> _ReportInputs:
        return _ReportInputs(
            compares={"base_sha": compare_files},
            review_comments=[comment] if comment else [],
            published=[
                _PublishedFinding(finding=_finding(), verdict=_verdict(), comment=comment, reviewed_head="base_sha")
            ],
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
            patch(f"{_CLASSIFY}.judge_finding", new=AsyncMock(return_value=_ruling(judge_return))) as judge,
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

    def test_the_judges_reasoning_is_persisted_with_the_outcome(self):
        # The ruling is the only record of why a finding was classified as it was; the diff it read
        # has moved on by the time anyone asks. It goes in the artefact rather than the event so the
        # explanation is durable without shipping free text to ClickHouse per finding.
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(1)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted"),
            patch(f"{_CLASSIFY}.judge_finding", new=AsyncMock(return_value=_ruling(True, "the guard now covers it"))),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: None,
            )

        assert [oc.judge_reasoning for oc in persist.call_args.kwargs["outcomes"]] == ["the guard now covers it"]

    def test_reasoning_is_capped_before_it_reaches_the_record(self):
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(1)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted"),
            patch(f"{_CLASSIFY}.judge_finding", new=AsyncMock(return_value=_ruling(True, "x" * 50_000))),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: None,
            )

        stored = persist.call_args.kwargs["outcomes"][0].judge_reasoning
        assert stored is not None and len(stored) == OUTCOME_JUDGE_REASONING_MAX_CHARS

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
        # Failures the judge itself raises are tolerated and recorded, but anything else partway
        # through must still leave no trace on either side: a partial artefact write would strand the
        # report's remaining findings, and any event emitted before the outcomes are durably decided
        # could conflict with what a retry re-decides (a human reply landing in the gap flips
        # `ignored` to `reacted`) — the double-row corruption the persist-first order exists to
        # prevent.
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(2)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted") as mark,
            patch(f"{_CLASSIFY}.touched_near", side_effect=RuntimeError("proximity blew up")),
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
                capture=lambda **kw: captured.append(kw),
                flush=lambda: order.append("flush"),
            )
        assert classified == 1
        assert captured[0]["properties"]["outcome"] == "reacted"
        assert captured[0]["properties"]["classification_method"] == "comment_reply"
        assert captured[0]["uuid"] == str(uuid5(NAMESPACE_URL, f"reviewhog_finding_outcome:{report.id}:{_ISSUE_KEY}"))
        assert order == ["flush", "mark"]

    def test_judge_calls_are_capped_per_report_and_spent_on_the_worst_findings(self):
        # Findings accumulate across every turn a PR was reviewed, so a PR pushed and re-reviewed
        # repeatedly can carry more candidates than the classify activity's budget. Judge calls run
        # sequentially and outcomes persist only after the whole report is decided, so an unbounded
        # report would blow the activity ceiling and every retry and later sweep would replay the
        # same calls without ever finishing it. Over the ceiling the rest settle unjudged, and the
        # budget goes to the most severe findings rather than whichever happened to be listed first.
        over = OUTCOME_MAX_JUDGE_CALLS_PER_REPORT + 3
        published = [
            _PublishedFinding(
                finding=_finding(
                    issue_key=f"r1:f.py:{i}:logic",
                    # The low-priority ones come first, so an uncapped or unordered pass would spend
                    # the budget on them and leave the must_fix findings unjudged.
                    priority=IssuePriority.CONSIDER if i < 4 else IssuePriority.MUST_FIX,
                ),
                verdict=_verdict(issue_key=f"r1:f.py:{i}:logic"),
                comment=None,
                reviewed_head="base_sha",
            )
            for i in range(over)
        ]
        inputs = _ReportInputs(
            compares={"base_sha": _TOUCHING},
            review_comments=[],
            published=published,
            distinct_id="user-distinct",
            judge_user_id=0,
        )
        captured, judge = self._run(inputs=inputs, judge_return=True)

        assert judge.await_count == OUTCOME_MAX_JUDGE_CALLS_PER_REPORT
        assert len(captured) == over  # every published finding still gets exactly one event
        by_method: dict[str, list[str]] = defaultdict(list)
        for event in captured:
            by_method[event["properties"]["classification_method"]].append(event["properties"]["priority"])
        assert len(by_method["judge_budget_exhausted"]) == 3
        # The unjudged remainder is the least severe, and stays `ignored` rather than inventing a fate.
        assert set(by_method["judge_budget_exhausted"]) == {"consider"}
        unjudged = [e for e in captured if e["properties"]["classification_method"] == "judge_budget_exhausted"]
        assert {e["properties"]["outcome"] for e in unjudged} == {"ignored"}

    def _candidates(self, count: int) -> _ReportInputs:
        return _ReportInputs(
            compares={"base_sha": _TOUCHING},
            review_comments=[],
            published=[
                _PublishedFinding(
                    finding=_finding(issue_key=f"r1:f.py:{i}:logic"),
                    verdict=_verdict(issue_key=f"r1:f.py:{i}:logic"),
                    comment=None,
                    reviewed_head="base_sha",
                )
                for i in range(count)
            ],
            distinct_id="user-distinct",
            judge_user_id=0,
        )

    def test_a_single_judge_failure_is_recorded_and_the_report_still_completes(self):
        # Nothing persists until the whole report is decided, so raising on one unanswerable finding
        # would discard the judgments already made and replay them every sweep, never finishing a
        # report that contains one. Recording it keeps the completed work and lets the report finish.
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(3)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted"),
            patch(
                f"{_CLASSIFY}.judge_finding",
                new=AsyncMock(side_effect=[_ruling(True), RuntimeError("gateway blip"), _ruling(False)]),
            ),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: captured.append(kw),
            )

        persist.assert_called_once()
        assert sorted(e["properties"]["classification_method"] for e in captured) == [
            "judge_confirmed",
            "judge_failed",
            "judge_rejected",
        ]

    def test_a_streak_of_judge_failures_abandons_the_report_without_persisting(self):
        # A run of failures means the judge itself is down. Outcomes are written once and never
        # re-decided, so finishing would permanently record this report as unjudgeable; skipping
        # leaves it for a sweep that can actually ask.
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(5)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(f"{_CLASSIFY}._mark_outcomes_emitted") as mark,
            patch(f"{_CLASSIFY}.judge_finding", new=AsyncMock(side_effect=RuntimeError("judge down"))) as judge,
            pytest.raises(_SkipReport),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: captured.append(kw),
            )

        assert judge.await_count == OUTCOME_JUDGE_FAILURE_STREAK  # stops spending once it looks down
        persist.assert_not_called()
        mark.assert_not_called()
        assert captured == []

    def test_intermittent_judge_failures_abandon_the_report_before_persisting(self):
        # Alternating failures never build a streak, so the ratio is the only thing that catches a
        # judge that is up but mostly failing. Without it the report would durably record a majority
        # of `judge_failed` outcomes that can never be re-decided.
        captured: list[dict[str, Any]] = []
        with (
            patch(f"{_CLASSIFY}._gather_report_inputs", return_value=self._candidates(5)),
            patch(f"{_CLASSIFY}._persist_outcomes") as persist,
            patch(
                f"{_CLASSIFY}.judge_finding",
                new=AsyncMock(
                    side_effect=[RuntimeError("a"), _ruling(True), RuntimeError("b"), _ruling(True), RuntimeError("c")]
                ),
            ),
            pytest.raises(_SkipReport),
        ):
            async_to_sync(classify_report)(
                team_id=1,
                report=ReviewReport(repository="o/r", pr_number=7),
                final_head="head_sha",
                capture=lambda **kw: captured.append(kw),
            )

        persist.assert_not_called()
        assert captured == []

    def test_one_report_failing_does_not_strand_the_rest_of_the_sweep(self):
        # The judge raises ApplicationError on any LLM failure, and a failed report writes no
        # completion stamp, so discovery hands it back every sweep. Letting that escape the loop
        # would abort the sweep at the same report forever and never classify the backlog behind it.
        failing = ReviewReport(repository="o/r", pr_number=7)
        healthy = ReviewReport(repository="o/r", pr_number=8)
        merged = [SimpleNamespace(number=7, head_sha="h7"), SimpleNamespace(number=8, head_sha="h8")]
        classify = AsyncMock(side_effect=[ApplicationError("judge died"), 1])
        with (
            patch(f"{_CLASSIFY}.unclassified_published_reports", return_value=[failing, healthy]),
            patch(f"{_CLASSIFY}._report_ids_with_persisted_outcomes", return_value=set()),
            patch(f"{_CLASSIFY}.list_recently_merged_pull_requests", return_value=merged),
            patch(f"{_CLASSIFY}.classify_report", new=classify),
        ):
            classified = async_to_sync(classify_team)(team=Team(id=1), capture=lambda **kw: None)

        assert classified == 1
        assert [call.kwargs["report"] for call in classify.await_args_list] == [failing, healthy]

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

        assert list(inputs.compares) == ["base_sha"]
        assert inputs.published[0].reviewed_head == "base_sha"
        assert [pf.finding.issue_key for pf in inputs.published] == [_ISSUE_KEY]
        assert inputs.published[0].comment == comment  # the finding was paired with its posted comment
        assert inputs.distinct_id == self.user.distinct_id

    def test_each_turn_is_compared_from_the_head_it_published_at(self):
        # A finding posted at turn 1 can be fixed by a commit that lands before turn 2 reviews. That
        # commit is outside a compare based at the newest published head, so measuring every finding
        # from there hides the fix and records a finding that was addressed as ignored.
        report = self._report()
        report.published_head_shas = {"1": "sha_turn_one", "2": "sha_turn_two"}
        report.published_head_sha = "sha_turn_two"
        report.save(update_fields=["published_head_shas", "published_head_sha"])
        turn_two = _finding(issue_key="r2:f.py:30:logic", title="Race", run_index=2)
        ReviewReportArtefact.append_finding(
            team_id=self.team.id, report_id=str(report.id), content=turn_two, attribution=ArtefactAttribution.system()
        )
        ReviewReportArtefact.append_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            content=_verdict(issue_key=turn_two.issue_key),
            attribution=ArtefactAttribution.system(),
        )
        bases: list[str] = []

        def _capture_base(*, base_sha: str, **kwargs: Any) -> list[dict[str, Any]]:
            bases.append(base_sha)
            return _TOUCHING

        with (
            patch(f"{_CLASSIFY}._installation_auth", return_value=("tok", "inst")),
            patch(f"{_CLASSIFY}.fetch_compare_files", side_effect=_capture_base),
            patch(f"{_CLASSIFY}.fetch_review_comments", return_value=[]),
        ):
            inputs = _gather_report_inputs(team_id=self.team.id, report=report, final_head="head_sha")

        assert sorted(bases) == ["sha_turn_one", "sha_turn_two"]
        assert {pf.finding.issue_key: pf.reviewed_head for pf in inputs.published} == {
            _ISSUE_KEY: "sha_turn_one",
            "r2:f.py:30:logic": "sha_turn_two",
        }

    def test_turns_published_before_heads_were_recorded_use_the_newest_head(self):
        # Reports published before the per-turn map existed carry no entry; they keep the single
        # newest-head compare rather than losing their compare entirely.
        report = self._report()
        with (
            patch(f"{_CLASSIFY}._installation_auth", return_value=("tok", "inst")),
            patch(f"{_CLASSIFY}.fetch_compare_files", return_value=_TOUCHING) as compare,
            patch(f"{_CLASSIFY}.fetch_review_comments", return_value=[]),
        ):
            inputs = _gather_report_inputs(team_id=self.team.id, report=report, final_head="head_sha")

        assert compare.call_count == 1
        assert [pf.reviewed_head for pf in inputs.published] == ["base_sha"]

    def test_published_set_uses_the_threshold_snapshotted_at_publish(self):
        # The user's live threshold can change between publish and the merge sweep; the classifier
        # must reconstruct the published set from the snapshot taken when the review was posted
        # (here must_fix), not from current settings (default consider, which would admit both).
        report = self._report()
        report.published_urgency_thresholds = {"1": IssuePriority.MUST_FIX.value}
        report.save(update_fields=["published_urgency_thresholds"])
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

    def test_each_turn_keeps_the_threshold_its_own_publish_used(self):
        # A report republishes as new commits land, and the user can tighten their threshold between
        # turns. Turn 1 posted a `consider` finding under the looser threshold; turn 2 published at
        # `must_fix`. Gating the cross-turn set on one threshold drops that turn-1 finding from
        # telemetry even though it is on the PR, and the report is stamped emitted so it never
        # returns to be classified later.
        report = self._report()
        report.published_urgency_thresholds = {
            "1": IssuePriority.CONSIDER.value,
            "2": IssuePriority.MUST_FIX.value,
        }
        report.save(update_fields=["published_urgency_thresholds"])
        turn_one_low = _finding(issue_key="r1:f.py:20:style", title="Nitpick", priority=IssuePriority.CONSIDER)
        turn_two_high = _finding(
            issue_key="r2:f.py:30:logic", title="Race", priority=IssuePriority.MUST_FIX, run_index=2
        )
        for content in (turn_one_low, turn_two_high):
            ReviewReportArtefact.append_finding(
                team_id=self.team.id,
                report_id=str(report.id),
                content=content,
                attribution=ArtefactAttribution.system(),
            )
            ReviewReportArtefact.append_verdict(
                team_id=self.team.id,
                report_id=str(report.id),
                content=_verdict(issue_key=content.issue_key),
                attribution=ArtefactAttribution.system(),
            )
        with (
            patch(f"{_CLASSIFY}._installation_auth", return_value=("tok", "inst")),
            patch(f"{_CLASSIFY}.fetch_compare_files", return_value=_FAR),
            patch(f"{_CLASSIFY}.fetch_review_comments", return_value=[]),
        ):
            inputs = _gather_report_inputs(team_id=self.team.id, report=report, final_head="head_sha")

        assert sorted(pf.finding.issue_key for pf in inputs.published) == [
            _ISSUE_KEY,
            "r1:f.py:20:style",
            "r2:f.py:30:logic",
        ]

    def test_discovery_slice_is_bounded_and_newest_first(self):
        # A report whose PR closes without merging never becomes classifiable and never gets stamped,
        # so it stays discoverable forever. Unbounded, that sediment is re-read and folded into the
        # warehouse lookup's `numbers` filter every sweep, before the per-sweep report cap applies.
        # Oldest-first would make the bound worse than the leak: the sediment would fill the slice
        # and starve live work permanently.
        for pr_number, age_minutes in ((1, 30), (2, 10), (3, 20)):
            report = ReviewReport.objects.for_team(self.team.id).create(
                team=self.team,
                repository="o/r",
                pr_number=pr_number,
                pr_url=f"https://github.com/o/r/pull/{pr_number}",
                head_branch=f"feat-{pr_number}",
                base_branch="main",
                acting_user=self.user,
                published_head_sha="base_sha",
            )
            ReviewReport.objects.for_team(self.team.id).filter(id=report.id).update(
                updated_at=timezone.now() - timedelta(minutes=age_minutes)
            )

        assert [r.pr_number for r in unclassified_published_reports(self.team.id, limit=2)] == [2, 3]

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
