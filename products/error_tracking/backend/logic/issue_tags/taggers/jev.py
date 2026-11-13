from collections.abc import Sequence

import structlog

from products.error_tracking.backend.logic.issue_summaries import is_ai_data_processing_approved
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, JevTaggerConfig
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer, TagContext
from products.error_tracking.backend.logic.severity_inference import SEVERITY_INFERENCE_MODEL
from products.error_tracking.backend.models import ErrorTrackingIssueTag
from products.ml_inference.backend.facade import api as ml_inference
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest, NoulAnswer
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)


class JevTagger:
    source = ErrorTrackingIssueTag.Source.JEV

    def applies(self, team_id: int) -> bool:
        return is_ai_data_processing_approved(team_id)

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Ask every tag question in one decision request. Raises the ml_inference gateway errors unchanged."""
        configs = {definition.key: _jev_config(definition) for definition in definitions}
        result = ml_inference.decide_when_available(
            DecisionRequest(
                team_id=context.issue.team_id,
                state=context.state,
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
            answers[definition.key] = TagAnswer(
                value=_value(configs[definition.key], answer.probability),
                probability=answer.probability,
                model=result.model,
                question_version=definition.question_version,
                set_by=None,
            )
        return answers


def _jev_config(definition: IssueTagDefinition) -> JevTaggerConfig:
    for tagger in definition.taggers:
        if isinstance(tagger, JevTaggerConfig):
            return tagger
    raise ValueError(f"the issue tag {definition.key!r} has no Jev tagger")


def _value(config: JevTaggerConfig, probability: float) -> bool | None:
    if probability >= config.yes_at:
        return True
    if probability <= config.no_at:
        return False
    return None
