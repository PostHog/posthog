import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase
from django.utils import timezone

from clickhouse_driver.errors import NetworkError
from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import rerun, runner
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.registry import (
    IssueTagDefinition,
    JevTaggerConfig,
    RuleTaggerConfig,
)
from products.error_tracking.backend.logic.issue_tags.rerun import (
    IssueTaggerRerun,
    _event_batches,
    _needs_rerun,
    _StaleIssue,
    rerun_issue_taggers,
)
from products.error_tracking.backend.logic.issue_tags.runner import IssueTaggingSkipReason
from products.error_tracking.backend.logic.issue_tags.taggers.base import Tagger
from products.error_tracking.backend.logic.issue_tags.taggers.rule import RuleTagger
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueTag,
    ErrorTrackingIssueTagRule,
    sync_issues_to_clickhouse,
)
from products.event_definitions.backend.models import PropertyDefinition, PropertyType
from products.ml_inference.backend.facade.contracts import (
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionResult,
    NoulAnswer,
)

Source = ErrorTrackingIssueTag.Source

DECIDE = "products.error_tracking.backend.logic.issue_tags.taggers.jev.ml_inference.decide_when_available"
SLEEP = "products.error_tracking.backend.logic.issue_tags.rerun.time.sleep"
QUERY = "products.error_tracking.backend.logic.issue_tags.rerun.execute_hogql_query"

RULE_ID = uuid.uuid4()
RULE_TAG = IssueTagDefinition(
    key="paid_plan",
    label="Paid plan",
    description="",
    question_version=2,
    enabled_flag=ISSUE_TAGS_FLAG,
    taggers=(RuleTaggerConfig(rule_id=RULE_ID, bytecode=[]),),
)
JEV_TAG = IssueTagDefinition(
    key="cause_in_trace",
    label="Cause in trace",
    description="",
    question_version=1,
    enabled_flag=ISSUE_TAGS_FLAG,
    taggers=(JevTaggerConfig(instructions="Is the cause in the trace?", yes_at=0.7, no_at=0.3),),
)

STACK_TRACE: dict[str, object] = {
    "$exception_list": [
        {
            "type": "TypeError",
            "value": "cart is undefined",
            "stacktrace": {
                "type": "resolved",
                "frames": [{"resolved_name": "submitOrder", "source": "src/checkout/cart.ts", "line": 42}],
            },
        }
    ]
}
JEV_ANSWER = DecisionResult(model="jevk5-0.2", answers={"cause_in_trace": NoulAnswer(probability=0.9)}, input_tokens=1)


def _row(source: Source, *, question_version: int, model: str | None) -> ErrorTrackingIssueTag:
    return ErrorTrackingIssueTag(source=source, question_version=question_version, model=model)


class TestNeedsRerun(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_row", RULE_TAG, None, True),
            ("a_person_answered", RULE_TAG, _row(Source.MANUAL, question_version=1, model=None), False),
            ("current_rule", RULE_TAG, _row(Source.RULE, question_version=2, model=str(RULE_ID)), False),
            ("edited_rule", RULE_TAG, _row(Source.RULE, question_version=1, model=str(RULE_ID)), True),
            ("rule_recreated_with_the_key", RULE_TAG, _row(Source.RULE, question_version=2, model="old-rule"), True),
            ("current_jev_question", JEV_TAG, _row(Source.JEV, question_version=1, model="jevk5-0.2"), False),
            ("changed_jev_question", JEV_TAG, _row(Source.JEV, question_version=0, model="jevk5-0.2"), True),
        ]
    )
    def test_reruns_a_tag_only_without_a_current_answer(
        self, _name: str, definition: IssueTagDefinition, row: ErrorTrackingIssueTag | None, expected: bool
    ) -> None:
        source = definition.taggers[0].source
        assert _needs_rerun(source, definition, row) is expected


class TestEventBatches(SimpleTestCase):
    @parameterized.expand(
        [
            ("an_old_issue_gets_its_own_batch", [1.0, 60.0, 1.5], 100, [[60.0], [1.5, 1.0]]),
            ("a_full_batch_starts_the_next", [1.0, 1.0, 1.0], 2, [[1.0, 1.0], [1.0]]),
        ]
    )
    def test_groups_issues_by_first_seen(
        self, _name: str, days_ago: list[float], batch_size: int, expected: list[list[float]]
    ) -> None:
        now = datetime(2026, 1, 31, tzinfo=UTC)
        issues = [
            _StaleIssue(id=uuid.uuid4(), first_seen=now - timedelta(days=days), taggers=(), keys=frozenset())
            for days in days_ago
        ]

        with patch.object(rerun, "BATCH_SIZE", batch_size):
            batches = list(_event_batches(issues))

        assert [[(now - issue.first_seen) / timedelta(days=1) for issue in batch] for batch in batches] == expected


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestRerunIssueTaggers(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        PropertyDefinition.objects.create(
            team=self.team, name="plan", type=PropertyDefinition.Type.EVENT, property_type=PropertyType.String
        )
        filters = {
            "type": "AND",
            "values": [
                {"type": "AND", "values": [{"key": "plan", "type": "event", "operator": "exact", "value": ["paid"]}]}
            ],
        }
        self.rule = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            key="paid_plan",
            label="Paid plan",
            filters=filters,
            bytecode=compile_filter_bytecode(self.team.id, filters),
            order_key=1,
        )

    def test_a_rule_labels_an_old_issue_from_its_first_exception_event(self) -> None:
        labelled = self._issue(days_ago=3)
        self._exception(labelled, {"plan": "paid"}, at=labelled.created_at - timedelta(seconds=5))
        self._exception(labelled, {"plan": "free"}, at=labelled.created_at + timedelta(minutes=10))
        unlabelled = self._issue(days_ago=2)
        self._exception(unlabelled, {"plan": "free"}, at=unlabelled.created_at - timedelta(seconds=5))
        self._exception(unlabelled, {"plan": "paid"}, at=unlabelled.created_at + timedelta(minutes=10))
        self._issue(days_ago=1)
        flush_persons_and_events()

        with patch(DECIDE, side_effect=AssertionError("no stack trace, so no model call")):
            result = self._rerun()

        assert result == IssueTaggerRerun(selected=3, ran=2, skipped=1, failed=0)
        assert list(self._labels()) == [(labelled.id, self.rule.key, Source.RULE, str(self.rule.id))]

    def test_a_split_issue_is_tagged_from_its_own_first_event(self) -> None:
        original = self._issue(days_ago=3)
        moved = f"moved-{original.id}"
        self._exception(original, {"plan": "paid"}, at=original.created_at - timedelta(seconds=5), fingerprint=moved)
        self._exception(original, {"plan": "free"}, at=original.created_at + timedelta(minutes=10))
        split = self._issue(days_ago=1)
        self._fingerprint(split, moved, first_seen=original.created_at - timedelta(seconds=5))
        flush_persons_and_events()

        result = self._rerun(taggers=(RuleTagger(),))

        assert result == IssueTaggerRerun(selected=2, ran=2, skipped=0, failed=0)
        assert [(issue_id, key) for issue_id, key, *_ in self._labels()] == [(split.id, "paid_plan")]

    def test_a_dry_run_counts_issues_without_a_current_answer_and_writes_nothing(self) -> None:
        answered = self._issue(days_ago=2)
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team,
            issue=answered,
            key=self.rule.key,
            value=True,
            source=Source.RULE,
            model=str(self.rule.id),
            question_version=self.rule.version,
        )
        self._issue(days_ago=1)
        self._issue(days_ago=1)
        self._issue(days_ago=8)
        self._issue(days_ago=1, status=ErrorTrackingIssue.Status.RESOLVED)

        with patch("products.error_tracking.backend.logic.issue_tags.rerun.execute_hogql_query") as query:
            result = self._rerun(dry_run=True, taggers=(RuleTagger(),))

        assert result == IssueTaggerRerun(selected=2, ran=0, skipped=0, failed=0)
        query.assert_not_called()
        assert ErrorTrackingIssueTag.objects.for_team(self.team.id).count() == 1

    def test_the_limit_caps_the_issues_newest_first(self) -> None:
        issues = [self._issue(days_ago=days_ago) for days_ago in (3, 2, 1)]
        for issue in issues:
            self._exception(issue, {"plan": "paid"}, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()

        with patch.object(rerun, "BATCH_SIZE", 1):
            result = self._rerun(limit=2)

        assert result == IssueTaggerRerun(selected=2, ran=2, skipped=0, failed=0)
        assert {issue_id for issue_id, *_ in self._labels()} == {issues[1].id, issues[2].id}

    @parameterized.expand([("transient_then_answers", 1, True), ("transient_on_every_attempt", 3, False)])
    def test_retries_a_transient_clickhouse_failure_on_the_event_read(
        self, _name: str, failures: int, answered: bool
    ) -> None:
        issue = self._issue(days_ago=1)
        self._exception(issue, {"plan": "paid"}, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()
        errors = iter([NetworkError("connection refused")] * failures)

        def flaky_query(*args: Any, **kwargs: Any) -> Any:
            if (error := next(errors, None)) is not None:
                raise error
            return execute_hogql_query(*args, **kwargs)

        with patch(QUERY, side_effect=flaky_query), patch(SLEEP):
            result = self._rerun(taggers=(RuleTagger(),))

        assert result == IssueTaggerRerun(selected=1, ran=int(answered), skipped=0, failed=int(not answered))
        assert [key for _, key, *_ in self._labels()] == (["paid_plan"] if answered else [])

    def test_paging_keeps_issues_created_at_the_same_time(self) -> None:
        issues = [self._issue(days_ago=1) for _ in range(3)]
        ErrorTrackingIssue.objects.filter(id__in=[issue.id for issue in issues]).update(created_at=issues[0].created_at)

        with patch.object(rerun, "BATCH_SIZE", 1):
            result = self._rerun(dry_run=True, taggers=(RuleTagger(),))

        assert result == IssueTaggerRerun(selected=3, ran=0, skipped=0, failed=0)

    @parameterized.expand(
        [
            ("rate_limited_then_answers", [DecisionGatewayError(429, "slow down")], True),
            ("rate_limited_on_every_attempt", [DecisionGatewayError(429, "slow down")] * 3, False),
            ("gateway_error_then_answers", [DecisionGatewayError(503, "unavailable")], True),
            ("unreachable_then_answers", [DecisionGatewayUnreachableError("timeout")], True),
            ("rejected", [DecisionGatewayError(422, "bad request")], False),
        ]
    )
    def test_retries_jev_while_the_model_is_unavailable(
        self, _name: str, errors: list[Exception], answered: bool
    ) -> None:
        issue = self._issue(days_ago=1)
        self._exception(issue, STACK_TRACE, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()

        with patch(DECIDE, side_effect=[*errors, JEV_ANSWER]), patch(SLEEP):
            result = self._rerun()

        assert result == IssueTaggerRerun(selected=1, ran=int(answered), skipped=0, failed=int(not answered))
        assert [key for _, key, *_ in self._labels()] == (["cause_in_trace"] if answered else [])

    @parameterized.expand(
        [
            ("rule_tagger_only", Source.RULE, None, ["paid_plan", "paid_plan_copy"]),
            ("jev_tag_only", None, "cause_in_trace", ["cause_in_trace"]),
            ("one_rule_tag_only", None, "paid_plan", ["paid_plan"]),
        ]
    )
    def test_a_rerun_limited_to_a_tagger_or_a_tag_runs_nothing_else(
        self, _name: str, source: Source | None, key: str | None, labels: list[str]
    ) -> None:
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            key="paid_plan_copy",
            label="Paid plan copy",
            filters=self.rule.filters,
            bytecode=self.rule.bytecode,
            order_key=2,
        )
        issue = self._issue(days_ago=1)
        self._exception(issue, {**STACK_TRACE, "plan": "paid"}, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()
        taggers = tuple(tagger for tagger in runner.TAGGERS if source is None or tagger.source == source)

        with patch(DECIDE, return_value=JEV_ANSWER) as decide:
            result = self._rerun(taggers=taggers, keys=None if key is None else [key])

        assert result == IssueTaggerRerun(selected=1, ran=1, skipped=0, failed=0)
        assert [label_key for _, label_key, *_ in self._labels()] == labels
        assert decide.called is ("cause_in_trace" in labels)

    def test_the_command_skips_a_team_with_issue_tags_off_and_reads_nothing(self) -> None:
        self._issue(days_ago=1)
        stdout = StringIO()

        with (
            patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: False),
            self.assertNumQueries(0),
        ):
            call_command("rerun_error_tracking_issue_taggers", "--team-id", str(self.team.id), stdout=stdout)

        assert stdout.getvalue() == f"Issue tags are off for team {self.team.id}, so nothing ran.\n"

    @parameterized.expand([("dry_run_by_default", [], False), ("live_run", ["--live-run"], True)])
    def test_the_command_writes_only_with_live_run(self, _name: str, flags: list[str], writes: bool) -> None:
        issue = self._issue(days_ago=1)
        self._exception(issue, {"plan": "paid"}, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()
        stdout = StringIO()

        call_command(
            "rerun_error_tracking_issue_taggers",
            "--team-id",
            str(self.team.id),
            "--tagger",
            "rule",
            *flags,
            stdout=stdout,
        )

        assert stdout.getvalue().startswith("Re-ran 1 of 1" if writes else "Dry run: 1 issues")
        assert [key for _, key, *_ in self._labels()] == (["paid_plan"] if writes else [])

    def test_the_command_rejects_a_tag_that_no_selected_tagger_answers(self) -> None:
        with self.assertRaisesMessage(CommandError, "cause_in_trace"):
            call_command(
                "rerun_error_tracking_issue_taggers",
                "--team-id",
                str(self.team.id),
                "--tagger",
                "rule",
                "--tag",
                "cause_in_trace",
                stdout=StringIO(),
            )

    def _rerun(
        self,
        *,
        limit: int = 100,
        dry_run: bool = False,
        taggers: tuple[Tagger, ...] = runner.TAGGERS,
        keys: list[str] | None = None,
    ) -> IssueTaggerRerun | IssueTaggingSkipReason:
        return rerun_issue_taggers(self.team.id, days=7, taggers=taggers, keys=keys, limit=limit, dry_run=dry_run)

    def _issue(
        self, *, days_ago: int, status: ErrorTrackingIssue.Status = ErrorTrackingIssue.Status.ACTIVE
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, status=status)
        ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=timezone.now() - timedelta(days=days_ago))
        issue.refresh_from_db()
        self._fingerprint(issue, f"fingerprint-{issue.id}")
        return issue

    def _fingerprint(self, issue: ErrorTrackingIssue, fingerprint: str, *, first_seen: datetime | None = None) -> None:
        row = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        # auto_now_add ignores a first_seen passed to create().
        ErrorTrackingIssueFingerprintV2.objects.filter(id=row.id).update(first_seen=first_seen or issue.created_at)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.id)

    def _exception(
        self,
        issue: ErrorTrackingIssue,
        properties: dict[str, object],
        *,
        at: datetime,
        fingerprint: str | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="user",
            properties={
                "$exception_issue_id": str(issue.id),
                "$exception_fingerprint": fingerprint or f"fingerprint-{issue.id}",
                **properties,
            },
            timestamp=at,
        )

    def _labels(self) -> list[tuple[uuid.UUID, str, str, str | None]]:
        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(value=True).order_by("issue_id", "key")
        return list(tags.values_list("issue_id", "key", "source", "model"))
