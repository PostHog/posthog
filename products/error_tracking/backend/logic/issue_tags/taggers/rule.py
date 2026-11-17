import time
from collections.abc import Sequence
from datetime import timedelta

from django.utils import timezone

import structlog

from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, RuleTaggerConfig
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer, TagContext
from products.error_tracking.backend.logic.rules import MAX_SEVERITY_RULE_BYTECODE_OPS
from products.error_tracking.backend.models import ErrorTrackingIssueTag, ErrorTrackingIssueTagRule

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, HOGQL_BYTECODE_IDENTIFIER_V0
from common.hogvm.python.stl import BLOCKING_FUNCTIONS

logger = structlog.get_logger(__name__)

# Cymbal limits severity rules in VM steps (rust/cymbal/src/modes/processing/rules/severity.rs). The Python VM
# limits only time, so these keep cymbal's ratio: one rule may use a tenth of the budget for all of an issue's rules.
RULE_TIMEOUT = timedelta(milliseconds=100)
ISSUE_RULES_BUDGET = timedelta(seconds=1)


def rule_globals(event_properties: dict[str, object]) -> dict[str, object]:
    """The input that every rule reads. Rules compile from event property filters, which read `properties`."""
    return {"properties": event_properties}


class RuleTagger:
    source = ErrorTrackingIssueTag.Source.RULE

    def __init__(self, *, rule_timeout: timedelta = RULE_TIMEOUT, issue_budget: timedelta = ISSUE_RULES_BUDGET) -> None:
        self.rule_timeout = rule_timeout
        self.issue_budget = issue_budget

    def applies(self, team_id: int) -> bool:
        # A rule makes no model call, so AI data processing approval does not gate it.
        return True

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Apply the label of each rule that matches the event. A miss answers nothing.

        A rule with broken bytecode is disabled, because it fails on every event. A rule that raises or runs past its
        timeout on this event counts as a miss and stays enabled, because the event can be the cause. When the issue's
        budget runs out, the remaining rules do not run.
        """
        rule_input = rule_globals(context.event_properties)
        deadline = time.monotonic() + self.issue_budget.total_seconds()
        answers: dict[str, TagAnswer] = {}
        for index, definition in enumerate(definitions):
            config = definition.tagger_config(RuleTaggerConfig)
            if (fault := _bytecode_fault(config.bytecode)) is not None:
                _disable(context, definition, config, fault)
                continue
            remaining = timedelta(seconds=deadline - time.monotonic())
            if remaining <= timedelta(0):
                _log_budget_exhausted(context, skipped=len(definitions) - index)
                break
            timeout = min(self.rule_timeout, remaining)
            try:
                matched = _matches(config, rule_input, timeout)
            except Exception as error:
                logger.warning(
                    "error_tracking_issue_tag_rule_failed",
                    team_id=context.issue.team_id,
                    issue_id=str(context.issue.id),
                    rule_id=str(config.rule_id),
                    # The message can quote an event property value, so it stays out of the log.
                    error_type=type(error).__name__,
                )
                continue
            if matched:
                answers[definition.key] = TagAnswer(
                    value=True,
                    probability=None,
                    model=str(config.rule_id),
                    question_version=definition.question_version,
                    set_by=None,
                )
        return answers


def _bytecode_fault(bytecode: object) -> str | None:
    """Why the bytecode cannot run for any event, or None when it can."""
    if not isinstance(bytecode, list) or bytecode[:1] not in (
        [HOGQL_BYTECODE_IDENTIFIER],
        [HOGQL_BYTECODE_IDENTIFIER_V0],
    ):
        return "Rule bytecode is not HogVM bytecode"
    if len(bytecode) > MAX_SEVERITY_RULE_BYTECODE_OPS:
        return f"Rule bytecode has {len(bytecode)} operations, maximum is {MAX_SEVERITY_RULE_BYTECODE_OPS}"
    return None


def _matches(config: RuleTaggerConfig, rule_input: dict[str, object], timeout: timedelta) -> bool:
    # Rules run on the shared worker, so a blocking call must not hold it.
    result = execute_bytecode(config.bytecode, rule_input, timeout=timeout, disallowed_functions=BLOCKING_FUNCTIONS)
    # A filter with an empty property group or value list compiles to the constant 1, which matches every event.
    return result.result is True or (type(result.result) is int and result.result == 1)


def _log_budget_exhausted(context: TagContext, *, skipped: int) -> None:
    logger.warning(
        "error_tracking_issue_tag_rules_budget_exhausted",
        team_id=context.issue.team_id,
        issue_id=str(context.issue.id),
        skipped=skipped,
    )


def _disable(context: TagContext, definition: IssueTagDefinition, config: RuleTaggerConfig, fault: str) -> None:
    # The version filter keeps a rule that a person edited during this run enabled, because the fault is in the
    # bytecode before the edit.
    ErrorTrackingIssueTagRule.objects.for_team(context.issue.team_id).filter(
        id=config.rule_id, version=definition.question_version
    ).update(
        disabled_data={"message": fault},
        updated_at=timezone.now(),
    )
    logger.warning(
        "error_tracking_issue_tag_rule_disabled",
        team_id=context.issue.team_id,
        issue_id=str(context.issue.id),
        rule_id=str(config.rule_id),
        fault=fault,
    )
