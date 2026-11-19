import uuid
from datetime import datetime, timedelta
from io import StringIO

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import runner
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.registry import (
    IssueTagDefinition,
    JevTaggerConfig,
    RuleTaggerConfig,
)
from products.error_tracking.backend.logic.issue_tags.rerun import IssueTaggerRerun, _needs_rerun, rerun_issue_taggers
from products.error_tracking.backend.logic.issue_tags.runner import IssueTaggingSkipReason
from products.error_tracking.backend.logic.issue_tags.taggers.base import Tagger
from products.error_tracking.backend.logic.issue_tags.taggers.rule import RuleTagger
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag, ErrorTrackingIssueTagRule
from products.event_definitions.backend.models import PropertyDefinition, PropertyType
from products.ml_inference.backend.facade.contracts import DecisionGatewayError, DecisionResult, NoulAnswer

Source = ErrorTrackingIssueTag.Source

DECIDE = "products.error_tracking.backend.logic.issue_tags.taggers.jev.ml_inference.decide_when_available"
SLEEP = "products.error_tracking.backend.logic.issue_tags.rerun.time.sleep"

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

        result = self._rerun(limit=2)

        assert result == IssueTaggerRerun(selected=2, ran=2, skipped=0, failed=0)
        assert {issue_id for issue_id, *_ in self._labels()} == {issues[1].id, issues[2].id}

    @parameterized.expand(
        [
            ("rate_limited_then_answers", [DecisionGatewayError(429, "slow down")], True, (1, 0)),
            ("rate_limited_on_every_attempt", [DecisionGatewayError(429, "slow down")] * 3, False, (0, 1)),
            ("rejected", [DecisionGatewayError(422, "bad request")], False, (0, 1)),
        ]
    )
    def test_retries_jev_while_the_model_is_unavailable(
        self, _name: str, errors: list[Exception], labelled: bool, ran_failed: tuple[int, int]
    ) -> None:
        issue = self._issue(days_ago=1)
        self._exception(issue, STACK_TRACE, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()
        answer = DecisionResult(
            model="jevk5-0.2", answers={"cause_in_trace": NoulAnswer(probability=0.9)}, input_tokens=1
        )

        with patch(DECIDE, side_effect=[*errors, answer]), patch(SLEEP):
            result = self._rerun()

        assert result == IssueTaggerRerun(selected=1, ran=ran_failed[0], skipped=0, failed=ran_failed[1])
        assert [key for _, key, *_ in self._labels()] == (["cause_in_trace"] if labelled else [])

    @parameterized.expand(
        [("rule_tagger_only", Source.RULE, None, False), ("jev_tag_only", None, "cause_in_trace", True)]
    )
    def test_a_rerun_limited_to_a_tagger_or_a_tag_runs_nothing_else(
        self, _name: str, source: Source | None, key: str | None, jev_labels: bool
    ) -> None:
        issue = self._issue(days_ago=1)
        self._exception(issue, {**STACK_TRACE, "plan": "paid"}, at=issue.created_at - timedelta(seconds=5))
        flush_persons_and_events()
        answer = DecisionResult(
            model="jevk5-0.2", answers={"cause_in_trace": NoulAnswer(probability=0.9)}, input_tokens=1
        )
        taggers = tuple(tagger for tagger in runner.TAGGERS if source in (None, tagger.source))

        with patch(DECIDE, return_value=answer) as decide:
            result = rerun_issue_taggers(
                self.team.id, days=7, taggers=taggers, keys=None if key is None else [key], limit=10, dry_run=False
            )

        assert result == IssueTaggerRerun(selected=1, ran=1, skipped=0, failed=0)
        assert [key for _, key, *_ in self._labels()] == ["cause_in_trace" if jev_labels else self.rule.key]
        assert decide.called is jev_labels

    def test_the_command_skips_a_team_with_issue_tags_off_and_reads_nothing(self) -> None:
        self._issue(days_ago=1)
        stdout = StringIO()

        with (
            patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: False),
            self.assertNumQueries(0),
        ):
            call_command("rerun_error_tracking_issue_taggers", "--team-id", str(self.team.id), stdout=stdout)

        assert stdout.getvalue() == f"Issue tags are off for team {self.team.id}, so nothing ran.\n"

    def _rerun(
        self, *, limit: int = 100, dry_run: bool = False, taggers: tuple[Tagger, ...] = runner.TAGGERS
    ) -> IssueTaggerRerun | IssueTaggingSkipReason:
        return rerun_issue_taggers(self.team.id, days=7, taggers=taggers, keys=None, limit=limit, dry_run=dry_run)

    def _issue(
        self, *, days_ago: int, status: ErrorTrackingIssue.Status = ErrorTrackingIssue.Status.ACTIVE
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, status=status)
        ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=timezone.now() - timedelta(days=days_ago))
        issue.refresh_from_db()
        return issue

    def _exception(self, issue: ErrorTrackingIssue, properties: dict[str, object], *, at: datetime) -> None:
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="user",
            properties={"$exception_issue_id": str(issue.id), **properties},
            timestamp=at,
        )

    def _labels(self) -> list[tuple[uuid.UUID, str, str, str | None]]:
        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(value=True).order_by("issue_id", "key")
        return list(tags.values_list("issue_id", "key", "source", "model"))
