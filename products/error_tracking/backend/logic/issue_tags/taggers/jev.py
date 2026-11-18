from collections.abc import Sequence

import structlog

from products.error_tracking.backend.logic.issue_summaries import is_ai_data_processing_approved
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, JevTaggerConfig
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer, TagContext
from products.error_tracking.backend.logic.severity_inference import SEVERITY_INFERENCE_MODEL, build_exception_state
from products.error_tracking.backend.models import ErrorTrackingIssueTag
from products.error_tracking.backend.temporal.lifecycle.rendering import render_stacktrace
from products.ml_inference.backend.facade import api as ml_inference
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest, NoulAnswer
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

TAG_STATE_MAX_TOKENS = 2000


class JevTagger:
    source = ErrorTrackingIssueTag.Source.JEV

    def applies(self, team_id: int) -> bool:
        return is_ai_data_processing_approved(team_id)

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Ask every tag question in one decision request. Raises the ml_inference gateway errors unchanged.

        Answer nothing, and make no model call, for an event without a stack trace.
        """
        stacktrace = render_stacktrace(context.event_properties, TAG_STATE_MAX_TOKENS)
        if not stacktrace:
            return {}
        configs = {definition.key: definition.tagger_config(JevTaggerConfig) for definition in definitions}
        result = ml_inference.decide_when_available(
            DecisionRequest(
                team_id=context.issue.team_id,
                state=build_exception_state(stacktrace, context.event_properties),
                questions={
                    key: DecisionQuestion(type=DecisionQuestionType.NOUL, instructions=config.instructions)
                    for key, config in configs.items()
                },
                model=SEVERITY_INFERENCE_MODEL,
                privacy_mode=True,
            )
        )
        answers: dict[str, TagAnswer] = {}
        for definition in definitions:
            answer = result.answers.get(definition.key)
            if not isinstance(answer, NoulAnswer):
                logger.warning(
                    "error_tracking_jev_tagger_unexpected_answer",
                    team_id=context.issue.team_id,
                    key=definition.key,
                    answer=repr(answer),
                )
                continue
            if answer.probability < configs[definition.key].yes_at:
                continue
            answers[definition.key] = TagAnswer(
                value=True,
                probability=answer.probability,
                model=result.model,
                question_version=definition.question_version,
                set_by=None,
            )
        return answers
