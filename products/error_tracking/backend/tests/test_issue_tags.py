import dataclasses
from typing import ClassVar, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic.issue_tags import registry, writer
from products.error_tracking.backend.logic.issue_tags.registry import (
    ISSUE_TAG_DEFINITIONS,
    IssueTagDefinition,
    JevTaggerConfig,
)
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag
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
    question_version=1,
    enabled_flag="error-tracking-issue-tags",
    taggers=(
        _NewTaggerConfig(),
        JevTaggerConfig(instructions="Does this error stop a user from paying?", yes_at=0.8, no_at=0.2),
    ),
)


class TestIssueTagRegistry(SimpleTestCase):
    def test_severity_and_every_jev_tag_fit_one_jev_request(self) -> None:
        jev_questions = sum(
            isinstance(tagger, JevTaggerConfig) for definition in ISSUE_TAG_DEFINITIONS for tagger in definition.taggers
        )

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
            ("jev_repeats_its_answer", Source.JEV, Source.JEV, True, True, 1),
            ("manual_confirms_jev", Source.JEV, Source.MANUAL, True, True, 2),
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
        set_issue_tag(self.team.id, issue.id, "blocks_checkout", self._answer(first, value=True), first)

        stored = set_issue_tag(
            self.team.id, issue.id, "blocks_checkout", self._answer(second, value=second_value), second
        )

        tag = ErrorTrackingIssueTag.objects.for_team(self.team.id).get(issue=issue, key="blocks_checkout")
        assert (stored, tag.source, tag.value) == ((True, second, second_value) if replaced else (False, first, True))
        assert self._issue_activity(issue).count() == logs

    def test_manual_replaces_an_answer_from_a_tagger_the_definition_no_longer_lists(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        set_issue_tag(self.team.id, issue.id, "blocks_checkout", self._answer(NEW_TAGGER, value=True), NEW_TAGGER)
        without_new_tagger = dataclasses.replace(BLOCKS_CHECKOUT, taggers=BLOCKS_CHECKOUT.taggers[1:])

        with patch.object(registry, "ISSUE_TAG_DEFINITIONS", (without_new_tagger,)):
            stored = set_issue_tag(
                self.team.id, issue.id, "blocks_checkout", self._answer(Source.MANUAL, value=False), Source.MANUAL
            )

        assert stored is True

    def test_stores_nothing_while_issue_tags_are_off_for_the_team(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with patch.object(writer, "issue_tags_enabled", new=lambda team_id: False):
            stored = set_issue_tag(
                self.team.id, issue.id, "blocks_checkout", self._answer(Source.MANUAL, value=True), Source.MANUAL
            )

        assert stored is False
        assert not ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).exists()
        assert not self._issue_activity(issue).exists()

    def test_a_failed_activity_log_write_rolls_back_the_tag(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with (
            self.settings(TEST=False, ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True),
            patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("write timed out")),
            self.assertRaises(IntegrityError),
        ):
            set_issue_tag(self.team.id, issue.id, "blocks_checkout", self._answer(Source.JEV, value=True), Source.JEV)

        assert not ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).exists()

    def test_logs_each_change_on_the_issue_with_the_person_for_a_manual_answer(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError: cart is undefined")

        set_issue_tag(self.team.id, issue.id, "blocks_checkout", self._answer(Source.JEV, value=False), Source.JEV)
        set_issue_tag(self.team.id, issue.id, "blocks_checkout", self._answer(Source.MANUAL, value=True), Source.MANUAL)

        changes_by_user = dict(self._issue_activity(issue).values_list("user_id", "detail__changes"))
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

    def _answer(self, source: ErrorTrackingIssueTag.Source, *, value: bool | None) -> TagAnswer:
        if source == Source.MANUAL:
            return TagAnswer(value=value, probability=None, model=None, question_version=1, set_by=self.user)
        return TagAnswer(value=value, probability=0.5, model=f"{source}-model", question_version=1, set_by=None)

    def _issue_activity(self, issue: ErrorTrackingIssue) -> QuerySet[ActivityLog]:
        return ActivityLog.objects.filter(team_id=self.team.id, scope="ErrorTrackingIssue", item_id=str(issue.id))
