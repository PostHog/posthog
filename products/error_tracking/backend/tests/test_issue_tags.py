import dataclasses
from typing import ClassVar, cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.models import QuerySet
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.kafka_client.client import ClickhouseProducer
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import registry, writer
from products.error_tracking.backend.logic.issue_tags.registry import (
    ISSUE_TAG_DEFINITIONS,
    IssueTagDefinition,
    JevTaggerConfig,
)
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueMergeResult,
    ErrorTrackingIssueTag,
)
from products.ml_inference.backend.facade.contracts import MAX_QUESTIONS_PER_REQUEST

Source = ErrorTrackingIssueTag.Source

# Stands for a tagger added later. A real one adds a Source value and a config class, and the writer does not change.
NEW_TAGGER = cast(ErrorTrackingIssueTag.Source, "new_tagger")


@frozen
class _NewTaggerConfig:
    source: ClassVar[ErrorTrackingIssueTag.Source] = NEW_TAGGER


BLOCKS_CHECKOUT = IssueTagDefinition(
    key="blocks_checkout",
    label="Blocks checkout",
    description="The error stops a user from paying.",
    question_version=1,
    enabled_flag="error-tracking-issue-tags",
    taggers=(
        _NewTaggerConfig(),
        JevTaggerConfig(instructions="Does this error stop a user from paying?", yes_at=0.8, no_at=0.2),
    ),
)


class TestIssueTagRegistry(SimpleTestCase):
    def test_every_jev_tag_fits_one_jev_request(self) -> None:
        jev_questions = sum(
            isinstance(tagger, JevTaggerConfig) for definition in ISSUE_TAG_DEFINITIONS for tagger in definition.taggers
        )

        # One slot stays free for the severity question, so the tag request and the severity request can merge.
        assert jev_questions + 1 <= MAX_QUESTIONS_PER_REQUEST


class TestIssueTagStorage(BaseTest):
    def test_an_issue_holds_one_answer_per_tag(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team, issue=issue, key="blocks_checkout", value=True, source="jev", question_version=1
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
                team=self.team, issue=issue, key="blocks_checkout", value=False, source="manual", question_version=1
            )


@patch.object(registry, "ISSUE_TAG_DEFINITIONS", (BLOCKS_CHECKOUT,))
@patch.object(writer, "issue_tags_enabled", new=lambda team_id: True)
class TestSetIssueTag(BaseTest):
    @parameterized.expand(
        [
            ("manual_replaces_jev", Source.JEV, Source.MANUAL, None, True, 2),
            ("jev_keeps_manual", Source.MANUAL, Source.JEV, None, False, 1),
            ("jev_replaces_jev", Source.JEV, Source.JEV, None, True, 2),
            ("new_tagger_replaces_jev", Source.JEV, NEW_TAGGER, None, True, 2),
            ("jev_keeps_new_tagger", NEW_TAGGER, Source.JEV, None, False, 1),
            ("new_tagger_keeps_manual", Source.MANUAL, NEW_TAGGER, None, False, 1),
            ("manual_confirms_jev", Source.JEV, Source.MANUAL, True, True, 2),
            ("manual_overrules_jev", Source.JEV, Source.MANUAL, False, True, 2),
        ]
    )
    def test_an_answer_replaces_only_sources_that_rank_no_higher(
        self,
        _name: str,
        first: ErrorTrackingIssueTag.Source,
        second: ErrorTrackingIssueTag.Source,
        second_value: bool | None,
        replaced: bool,
        logs: int,
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        with time_machine.travel("2026-01-05T10:00:00Z", tick=False), self.captureOnCommitCallbacks(execute=True):
            set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(first, value=True), first)
        _, first_version = _latest_clickhouse_answer(issue)

        with time_machine.travel("2026-01-05T10:01:00Z", tick=False), self.captureOnCommitCallbacks(execute=True):
            stored = set_issue_tag(
                self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(second, value=second_value), second
            )

        tag = ErrorTrackingIssueTag.objects.for_team(self.team.id).get(issue=issue, key="blocks_checkout")
        assert (stored, tag.source, tag.value) == ((True, second, second_value) if replaced else (False, first, True))
        assert _issue_activity(issue).count() == logs
        value, version = _latest_clickhouse_answer(issue)
        assert value == tag.value
        assert (version > first_version) is replaced

    @parameterized.expand(
        [
            ("same_answer", 1, ["SELECT"], 0),
            ("new_question_version", 2, ["SELECT", "UPDATE"], 1),
        ]
    )
    def test_a_repeated_answer_is_written_and_synced_only_when_it_changed(
        self, _name: str, question_version: int, expected_statements: list[str], expected_produces: int
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        answer = self._answer(Source.JEV, value=True)
        set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, answer, Source.JEV)
        repeat = dataclasses.replace(answer, question_version=question_version)
        produced: list[dict[str, object]] = []

        with (
            patch.object(ClickhouseProducer, "produce", side_effect=lambda **kwargs: produced.append(kwargs["data"])),
            self.captureOnCommitCallbacks(execute=True),
            CaptureQueriesContext(connection) as queries,
        ):
            stored = set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, repeat, Source.JEV)

        tag_statements = [
            query["sql"].split()[0]
            for query in queries.captured_queries
            if "posthog_errortrackingissuetag" in query["sql"]
        ]
        assert (stored, tag_statements, len(produced)) == (True, expected_statements, expected_produces)
        assert _issue_activity(issue).count() == 1

    def test_a_later_write_wins_in_clickhouse_when_its_clock_reads_earlier(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        with time_machine.travel("2026-01-05T10:01:00Z", tick=False), self.captureOnCommitCallbacks(execute=True):
            set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.JEV, value=True), Source.JEV)
        _, first_version = _latest_clickhouse_answer(issue)

        with time_machine.travel("2026-01-05T10:00:00Z", tick=False), self.captureOnCommitCallbacks(execute=True):
            set_issue_tag(
                self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.MANUAL, value=False), Source.MANUAL
            )

        value, version = _latest_clickhouse_answer(issue)
        assert (value, version > first_version) == (False, True)

    def test_manual_replaces_an_answer_from_a_tagger_the_definition_no_longer_lists(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(NEW_TAGGER, value=True), NEW_TAGGER)
        without_new_tagger = dataclasses.replace(BLOCKS_CHECKOUT, taggers=BLOCKS_CHECKOUT.taggers[1:])

        stored = set_issue_tag(
            self.team.id, issue.id, without_new_tagger, self._answer(Source.MANUAL, value=False), Source.MANUAL
        )

        assert stored is True

    def test_stores_nothing_while_issue_tags_are_off_for_the_team(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with patch.object(writer, "issue_tags_enabled", new=lambda team_id: False):
            stored = set_issue_tag(
                self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.MANUAL, value=True), Source.MANUAL
            )

        assert stored is False
        assert not ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).exists()
        assert not _issue_activity(issue).exists()

    def test_a_failed_activity_log_write_rolls_back_the_tag(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with (
            self.settings(TEST=False, ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True),
            patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("write timed out")),
            self.assertRaises(IntegrityError),
        ):
            set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.JEV, value=True), Source.JEV)

        assert not ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).exists()

    def test_logs_each_change_on_the_issue_with_the_person_for_a_manual_answer(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError: cart is undefined")

        set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.JEV, value=False), Source.JEV)
        set_issue_tag(self.team.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.MANUAL, value=True), Source.MANUAL)

        changes_by_user = dict(_issue_activity(issue).values_list("user_id", "detail__changes"))
        jev_answer = {"key": "blocks_checkout", "value": False, "source": "jev"}
        manual_answer = {"key": "blocks_checkout", "value": True, "source": "manual"}
        assert changes_by_user == {
            None: [
                {"type": "ErrorTrackingIssue", "action": "created", "field": "tag", "before": None, "after": jev_answer}
            ],
            self.user.id: [
                {
                    "type": "ErrorTrackingIssue",
                    "action": "changed",
                    "field": "tag",
                    "before": jev_answer,
                    "after": manual_answer,
                }
            ],
        }

    def test_a_child_environment_issue_keeps_one_answer_across_writes(self) -> None:
        child = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Staging"
        )
        issue = ErrorTrackingIssue.objects.create(team=child)

        set_issue_tag(child.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.JEV, value=False), Source.JEV)
        stored = set_issue_tag(child.id, issue.id, BLOCKS_CHECKOUT, self._answer(Source.JEV, value=True), Source.JEV)

        tag = ErrorTrackingIssueTag.objects.for_team(child.id).get(issue=issue, key="blocks_checkout")
        assert (stored, tag.value) == (True, True)

    def _answer(self, source: ErrorTrackingIssueTag.Source, *, value: bool | None) -> TagAnswer:
        if source == Source.MANUAL:
            return TagAnswer(value=value, probability=None, model=None, question_version=1, set_by=self.user)
        return TagAnswer(value=value, probability=0.5, model=f"{source}-model", question_version=1, set_by=None)


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestCarryIssueTagsOnMerge(BaseTest):
    @parameterized.expand(
        [
            ("tagger_label_moves", None, [(Source.JEV, True)], (Source.JEV, True)),
            ("manual_removal_on_target_stays", (Source.MANUAL, False), [(Source.JEV, True)], (Source.MANUAL, False)),
            ("manual_removal_on_source_is_not_carried", None, [(Source.MANUAL, False)], None),
            (
                "removal_on_one_source_does_not_hide_a_label_on_another",
                None,
                [(Source.MANUAL, False), (Source.JEV, True)],
                (Source.JEV, True),
            ),
            ("manual_label_replaces_tagger_label", (Source.JEV, True), [(Source.MANUAL, True)], (Source.MANUAL, True)),
            ("tagger_label_replaces_tagger_no", (Source.JEV, False), [(Source.JEV, True)], (Source.JEV, True)),
            (
                "tagger_label_already_on_target_is_left_alone",
                (Source.JEV, True),
                [(Source.JEV, True)],
                (Source.JEV, True),
            ),
            (
                "manual_label_on_a_later_source_replaces_tagger_label",
                None,
                [(Source.JEV, True), (Source.MANUAL, True)],
                (Source.MANUAL, True),
            ),
            (
                "tagger_label_on_a_later_source_does_not_replace_manual_label",
                None,
                [(Source.MANUAL, True), (Source.JEV, True)],
                (Source.MANUAL, True),
            ),
        ]
    )
    def test_merge_carries_applied_labels_unless_a_person_answered_on_the_target(
        self,
        _name: str,
        on_target: tuple[ErrorTrackingIssueTag.Source, bool] | None,
        on_sources: list[tuple[ErrorTrackingIssueTag.Source, bool]],
        expected: tuple[ErrorTrackingIssueTag.Source, bool] | None,
    ) -> None:
        target = ErrorTrackingIssue.objects.create(team=self.team)
        if on_target is not None:
            self._tag(target, *on_target)
        sources = [ErrorTrackingIssue.objects.create(team=self.team) for _ in on_sources]
        for source, (source_tag, value) in zip(sources, on_sources):
            self._tag(source, source_tag, value)

        target.merge([source.id for source in sources])

        assert self._target_answer(target) == expected
        assert _issue_activity(target).count() == int(expected != on_target)

    @parameterized.expand(
        [
            ("rule_label_from_a_source", None, Source.RULE, []),
            (
                "manual_label_over_a_rule_label",
                Source.RULE,
                Source.MANUAL,
                [
                    {
                        "type": "ErrorTrackingIssue",
                        "action": "created",
                        "field": "tag",
                        "before": None,
                        "after": {"key": "blocks_checkout", "value": True, "source": "manual"},
                    }
                ],
            ),
        ]
    )
    def test_the_activity_log_holds_no_rule_answer_that_a_merge_carries_or_replaces(
        self,
        _name: str,
        on_target: ErrorTrackingIssueTag.Source | None,
        on_source: ErrorTrackingIssueTag.Source,
        logged: list[dict[str, object]],
    ) -> None:
        target = ErrorTrackingIssue.objects.create(team=self.team)
        if on_target is not None:
            self._tag(target, on_target, True)
        source = ErrorTrackingIssue.objects.create(team=self.team)
        self._tag(source, on_source, True)

        target.merge([source.id])

        assert self._target_answer(target) == (on_source, True)
        assert [
            change for entry in _issue_activity(target) for change in (entry.detail or {}).get("changes", [])
        ] == logged

    def test_a_carried_label_is_logged_on_the_target_and_reaches_clickhouse(self) -> None:
        target = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError: cart is undefined")
        source = ErrorTrackingIssue.objects.create(team=self.team)
        self._tag(source, Source.JEV, True)

        with self.captureOnCommitCallbacks(execute=True):
            target.merge([source.id])

        assert dict(_issue_activity(target).values_list("user_id", "detail__changes")) == {
            None: [
                {
                    "type": "ErrorTrackingIssue",
                    "action": "created",
                    "field": "tag",
                    "before": None,
                    "after": {"key": "blocks_checkout", "value": True, "source": "jev"},
                }
            ],
        }
        assert _latest_clickhouse_answer(target)[0] is True

    def test_a_failed_activity_log_write_does_not_undo_the_merge(self) -> None:
        target = ErrorTrackingIssue.objects.create(team=self.team)
        source = ErrorTrackingIssue.objects.create(team=self.team)
        self._tag(source, Source.JEV, True)

        with (
            self.settings(TEST=False, ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True),
            patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("write timed out")),
        ):
            outcome = target.merge([source.id])

        assert outcome.result == ErrorTrackingIssueMergeResult.MERGED
        assert self._target_answer(target) == (Source.JEV, True)

    def test_carries_a_label_between_issues_of_a_child_environment(self) -> None:
        child = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Staging"
        )
        target = ErrorTrackingIssue.objects.create(team=child)
        source = ErrorTrackingIssue.objects.create(team=child)
        self._tag(source, Source.JEV, True)

        target.merge([source.id])

        assert self._target_answer(target) == (Source.JEV, True)

    def test_reads_no_tag_rows_while_issue_tags_are_off_for_the_team(self) -> None:
        target = ErrorTrackingIssue.objects.create(team=self.team)
        source = ErrorTrackingIssue.objects.create(team=self.team)
        self._tag(source, Source.JEV, True)

        with (
            patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: False),
            CaptureQueriesContext(connection) as queries,
        ):
            target.merge([source.id])

        tag_queries = [
            query["sql"] for query in queries.captured_queries if "posthog_errortrackingissuetag" in query["sql"]
        ]
        assert [sql.split()[0] for sql in tag_queries] == ["DELETE"]
        assert self._target_answer(target) is None

    def _tag(self, issue: ErrorTrackingIssue, source: ErrorTrackingIssueTag.Source, value: bool) -> None:
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=issue.team,
            issue=issue,
            key="blocks_checkout",
            value=value,
            source=source,
            question_version=1,
            set_by=self.user if source == Source.MANUAL else None,
        )

    def _target_answer(self, target: ErrorTrackingIssue) -> tuple[str, bool | None] | None:
        return (
            ErrorTrackingIssueTag.objects.for_team(self.team.id)
            .filter(issue=target, key="blocks_checkout")
            .values_list("source", "value")
            .first()
        )


def _issue_activity(issue: ErrorTrackingIssue) -> QuerySet[ActivityLog]:
    return ActivityLog.objects.filter(team_id=issue.team_id, scope="ErrorTrackingIssue", item_id=str(issue.id))


def _latest_clickhouse_answer(issue: ErrorTrackingIssue) -> tuple[bool | None, int]:
    response = execute_hogql_query(
        """
        SELECT value, version FROM posthog.raw_error_tracking_issue_tags
        WHERE issue_id = {issue_id} AND key = 'blocks_checkout'
        ORDER BY version DESC
        LIMIT 1
        """,
        issue.team,
        placeholders={"issue_id": ast.Constant(value=str(issue.id))},
    )
    [(value, version)] = response.results
    return None if value is None else bool(value), version
