import uuid
from collections.abc import Sequence
from typing import ClassVar, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.posthog_client import is_expected_activity_failure

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags import registry, runner
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, JevTaggerConfig
from products.error_tracking.backend.logic.issue_tags.runner import IssueTaggingSkipReason, TaggerRun, run_issue_taggers
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer, TagContext
from products.error_tracking.backend.logic.issue_tags.taggers.jev import JevTagger
from products.error_tracking.backend.logic.severity_inference import SEVERITY_INFERENCE_MODEL
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag
from products.error_tracking.backend.temporal.lifecycle.event_properties import IssueCreatedEventNotFoundError
from products.error_tracking.backend.temporal.lifecycle.issue_created.activities import tag_issue_created_activity
from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    ISSUE_TAGS_UNAVAILABLE_ERROR_TYPE,
    IssueCreatedSnapshot,
    IssueCreatedWorkflowInputs,
)
from products.ml_inference.backend.facade.contracts import (
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType

Source = ErrorTrackingIssueTag.Source

DECIDE = "products.error_tracking.backend.logic.issue_tags.taggers.jev.ml_inference.decide_when_available"
ACTIVITIES = "products.error_tracking.backend.temporal.lifecycle.issue_created.activities"

EVENT_PROPERTIES: dict[str, object] = {
    "$exception_list": [
        {
            "type": "TypeError",
            "value": "cart is undefined",
            "stacktrace": {
                "type": "resolved",
                "frames": [{"resolved_name": "submitOrder", "source": "src/checkout/cart.ts", "line": 42}],
            },
        }
    ],
    "$exception_level": "error",
}

BLOCKS_CHECKOUT = IssueTagDefinition(
    key="blocks_checkout",
    label="Blocks checkout",
    description="The error stops a user from paying.",
    question_version=2,
    enabled_flag="error-tracking-issue-tags",
    taggers=(JevTaggerConfig(instructions="Does this error stop a user from paying?", yes_at=0.8, no_at=0.2),),
)
RETRIES_ITSELF = IssueTagDefinition(
    key="retries_itself",
    label="Retries itself",
    description="The application retries the failed call by itself.",
    question_version=1,
    enabled_flag="error-tracking-issue-tags",
    taggers=(
        JevTaggerConfig(instructions="Does the application retry the failed call by itself?", yes_at=0.6, no_at=0.4),
    ),
)

NEW_TAGGER = cast(ErrorTrackingIssueTag.Source, "new_tagger")


@frozen
class _NewTaggerConfig:
    source: ClassVar[ErrorTrackingIssueTag.Source] = NEW_TAGGER


class _FailingTagger:
    source = NEW_TAGGER

    def __init__(self, error: Exception) -> None:
        self.error = error

    def applies(self, team_id: int) -> bool:
        return True

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        raise self.error


def _decision(answers: dict[str, NoulAnswer]) -> DecisionResult:
    return DecisionResult(model="jev-model", answers=dict(answers), input_tokens=10)


class TestJevTagger(SimpleTestCase):
    @parameterized.expand(
        [
            ("at_yes_threshold", 0.8, True),
            ("between_thresholds", 0.5, None),
            ("at_no_threshold", 0.2, False),
        ]
    )
    def test_maps_the_probability_through_the_tag_thresholds(
        self, _name: str, probability: float, expected: bool | None
    ) -> None:
        with patch(DECIDE, return_value=_decision({"blocks_checkout": NoulAnswer(probability=probability)})):
            answers = JevTagger().answer(self._context(), [BLOCKS_CHECKOUT])

        assert answers == {
            "blocks_checkout": TagAnswer(
                value=expected, probability=probability, model="jev-model", question_version=2, set_by=None
            )
        }

    def test_asks_every_tag_in_one_private_request_and_leaves_out_an_unanswered_tag(self) -> None:
        with patch(DECIDE, return_value=_decision({"blocks_checkout": NoulAnswer(probability=0.9)})) as decide:
            answers = JevTagger().answer(self._context(), [BLOCKS_CHECKOUT, RETRIES_ITSELF])

        request = decide.call_args.args[0]
        assert request.questions == {
            "blocks_checkout": DecisionQuestion(
                type=DecisionQuestionType.NOUL, instructions="Does this error stop a user from paying?"
            ),
            "retries_itself": DecisionQuestion(
                type=DecisionQuestionType.NOUL, instructions="Does the application retry the failed call by itself?"
            ),
        }
        assert (request.state, request.privacy_mode, request.model) == (
            "TypeError: cart is undefined",
            True,
            SEVERITY_INFERENCE_MODEL,
        )
        assert list(answers) == ["blocks_checkout"]

    def _context(self) -> TagContext:
        return TagContext(issue=ErrorTrackingIssue(team_id=1), state="TypeError: cart is undefined")


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestRunIssueTaggers(BaseTest):
    def test_stores_the_jev_answer_to_cause_in_trace(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with patch(DECIDE, return_value=_decision({"cause_in_trace": NoulAnswer(probability=0.9)})) as decide:
            result = run_issue_taggers(self.team.id, issue.id, lambda team: EVENT_PROPERTIES)

        assert result == (TaggerRun(source=Source.JEV),)
        assert decide.call_args.args[0].state == (
            "TypeError: cart is undefined\nsubmitOrder in src/checkout/cart.ts line 42\nLevel: error"
        )
        tag = ErrorTrackingIssueTag.objects.for_team(self.team.id).get(issue=issue)
        assert (tag.key, tag.value, tag.probability, tag.source, tag.model) == (
            "cause_in_trace",
            True,
            0.9,
            Source.JEV,
            "jev-model",
        )

    @parameterized.expand(
        [
            ("issue_tags_off", False, True, IssueTaggingSkipReason.DISABLED),
            ("ai_data_processing_not_approved", True, False, IssueTaggingSkipReason.NO_TAGGER),
        ]
    )
    def test_reads_no_event_and_asks_no_model_when_no_tagger_applies(
        self, _name: str, flag_on: bool, ai_approved: bool, expected: IssueTaggingSkipReason
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        load_event_properties = MagicMock(return_value=EVENT_PROPERTIES)

        with (
            patch.object(team_flags, "feature_enabled_or_false", return_value=flag_on),
            patch(DECIDE) as decide,
        ):
            result = run_issue_taggers(self.team.id, issue.id, load_event_properties)

        assert result == expected
        load_event_properties.assert_not_called()
        decide.assert_not_called()

    def test_a_failing_tagger_does_not_stop_the_next_one(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        error = RuntimeError("tagger bug")
        definition = IssueTagDefinition(
            key="cause_in_trace",
            label="Cause in trace",
            description="The stack trace shows where in your code the error starts.",
            question_version=1,
            enabled_flag="error-tracking-issue-tags",
            taggers=(
                _NewTaggerConfig(),
                JevTaggerConfig(instructions="Is the cause in the trace?", yes_at=0.7, no_at=0.3),
            ),
        )

        with (
            patch.object(registry, "ISSUE_TAG_DEFINITIONS", (definition,)),
            patch.object(runner, "TAGGERS", (_FailingTagger(error), JevTagger())),
            patch(DECIDE, return_value=_decision({"cause_in_trace": NoulAnswer(probability=0.1)})),
        ):
            result = run_issue_taggers(self.team.id, issue.id, lambda team: EVENT_PROPERTIES)

        assert result == (
            TaggerRun(source=NEW_TAGGER, error=error),
            TaggerRun(source=Source.JEV),
        )
        assert ErrorTrackingIssueTag.objects.for_team(self.team.id).get(issue=issue).value is False

    def test_returns_cleanly_when_a_merge_removes_the_issue_while_jev_answers(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        def merge_then_answer(_: object) -> DecisionResult:
            ErrorTrackingIssue.objects.filter(id=issue.id).delete()
            return _decision({"cause_in_trace": NoulAnswer(probability=0.9)})

        with patch(DECIDE, side_effect=merge_then_answer):
            result = run_issue_taggers(self.team.id, issue.id, lambda team: EVENT_PROPERTIES)

        assert result == IssueTaggingSkipReason.ISSUE_MISSING


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestTagIssueCreatedActivity(BaseTest):
    @parameterized.expand(
        [
            ("rate_limited", DecisionGatewayError(429, "rate limited"), ApplicationError, "unavailable"),
            ("gateway_down", DecisionGatewayError(503, "unavailable"), ApplicationError, "unavailable"),
            ("unreachable", DecisionGatewayUnreachableError("timeout"), ApplicationError, "unavailable"),
            ("tagger_bug", ValueError("malformed answer"), ValueError, "failed"),
            ("rejected", DecisionGatewayError(422, "bad request"), None, "gateway_rejected"),
            ("decisions_off", DecisionsDisabledError(1), None, "decisions_unavailable"),
        ]
    )
    def test_retries_a_transient_failure_or_a_bug_and_skips_the_rest(
        self, _name: str, decide_error: Exception, raises: type[Exception] | None, outcome: str
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with (
            patch(f"{ACTIVITIES}.fetch_event_properties", return_value=EVENT_PROPERTIES),
            patch(DECIDE, side_effect=decide_error),
            patch(f"{ACTIVITIES}.ERROR_TRACKING_ISSUE_TAGGER_OUTCOMES") as outcomes,
        ):
            if raises is None:
                tag_issue_created_activity(self._inputs(issue))
            else:
                with self.assertRaises(raises) as raised:
                    tag_issue_created_activity(self._inputs(issue))
                if isinstance(raised.exception, ApplicationError):
                    assert raised.exception.type == ISSUE_TAGS_UNAVAILABLE_ERROR_TYPE
                    assert not raised.exception.non_retryable
                    assert is_expected_activity_failure(raised.exception)

        outcomes.labels.assert_called_once_with(tagger="jev", outcome=outcome)
        outcomes.labels.return_value.inc.assert_called_once_with()
        assert not ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=issue).exists()

    def test_skips_without_a_retry_when_the_exception_event_is_missing(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with (
            patch(f"{ACTIVITIES}.fetch_event_properties", side_effect=IssueCreatedEventNotFoundError("gone")),
            patch(DECIDE) as decide,
            patch(f"{ACTIVITIES}.ERROR_TRACKING_ISSUE_TAGGER_OUTCOMES") as outcomes,
        ):
            tag_issue_created_activity(self._inputs(issue))

        outcomes.labels.assert_called_once_with(tagger="none", outcome="event_missing")
        decide.assert_not_called()

    def _inputs(self, issue: ErrorTrackingIssue) -> IssueCreatedWorkflowInputs:
        return IssueCreatedWorkflowInputs(
            notification_id=str(uuid.uuid4()),
            team_id=self.team.id,
            issue_id=str(issue.id),
            issue=IssueCreatedSnapshot(
                name="TypeError", description=None, status="active", created_at="2026-07-21T12:00:00Z"
            ),
            fingerprint="fingerprint",
            event_uuid=str(uuid.uuid4()),
            event_timestamp="2026-07-21T12:00:00Z",
        )
