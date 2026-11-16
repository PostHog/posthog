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
from common.hogvm.python.stl import BLOCKING_FUNCTIONS
from common.hogvm.python.utils import HogVMRuntimeExceededException

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

        A rule that raises, or runs past its own timeout, is disabled and the other rules still run. When the issue's
        budget runs out, the remaining rules do not run and stay enabled.
        """
        rule_input = rule_globals(context.event_properties)
        deadline = time.monotonic() + self.issue_budget.total_seconds()
        answers: dict[str, TagAnswer] = {}
        for index, definition in enumerate(definitions):
            config = _rule_config(definition)
            remaining = timedelta(seconds=deadline - time.monotonic())
            if remaining <= timedelta(0):
                _log_budget_exhausted(context, skipped=len(definitions) - index)
                break
            timeout = min(self.rule_timeout, remaining)
            try:
                matched = _matches(config, rule_input, timeout)
            except HogVMRuntimeExceededException as error:
                if timeout < self.rule_timeout:
                    # The issue's budget ran out during this rule, so the rule itself is not at fault.
                    _log_budget_exhausted(context, skipped=len(definitions) - index)
                    break
                _disable(context, definition, config, error)
                continue
            except Exception as error:
                _disable(context, definition, config, error)
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


def _rule_config(definition: IssueTagDefinition) -> RuleTaggerConfig:
    for tagger in definition.taggers:
        if isinstance(tagger, RuleTaggerConfig):
            return tagger
    raise ValueError(f"the issue tag {definition.key!r} has no rule")


def _matches(config: RuleTaggerConfig, rule_input: dict[str, object], timeout: timedelta) -> bool:
    if len(config.bytecode) > MAX_SEVERITY_RULE_BYTECODE_OPS:
        raise ValueError(
            f"Rule bytecode has {len(config.bytecode)} operations, maximum is {MAX_SEVERITY_RULE_BYTECODE_OPS}"
        )
    # Rules run on the shared worker, so a blocking call must not hold it.
    result = execute_bytecode(config.bytecode, rule_input, timeout=timeout, disallowed_functions=BLOCKING_FUNCTIONS)
    return result.result is True


def _log_budget_exhausted(context: TagContext, *, skipped: int) -> None:
    logger.warning(
        "error_tracking_issue_tag_rules_budget_exhausted",
        team_id=context.issue.team_id,
        issue_id=str(context.issue.id),
        skipped=skipped,
    )


def _disable(context: TagContext, definition: IssueTagDefinition, config: RuleTaggerConfig, error: Exception) -> None:
    # The version filter keeps a rule that a person edited during this run enabled, because the error came from
    # the bytecode before the edit.
    ErrorTrackingIssueTagRule.objects.for_team(context.issue.team_id).filter(
        id=config.rule_id, version=definition.question_version
    ).update(
        disabled_data={
            "message": str(error),
            "issue": {"id": str(context.issue.id)},
            "properties": context.event_properties,
        },
        updated_at=timezone.now(),
    )
    logger.warning(
        "error_tracking_issue_tag_rule_disabled",
        team_id=context.issue.team_id,
        issue_id=str(context.issue.id),
        rule_id=str(config.rule_id),
        error=str(error),
    )
