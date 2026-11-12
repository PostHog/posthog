from collections.abc import Callable
from enum import StrEnum
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.error_tracking.backend.logic.issue_tags import registry
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagContext, Tagger
from products.error_tracking.backend.logic.issue_tags.taggers.jev import JevTagger
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.logic.severity_inference import build_severity_state
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag
from products.error_tracking.backend.temporal.lifecycle.rendering import render_stacktrace

logger = structlog.get_logger(__name__)

TAGGERS: tuple[Tagger, ...] = (JevTagger(),)
TAG_STATE_MAX_TOKENS = 2000


class IssueTaggingSkipReason(StrEnum):
    DISABLED = "disabled"
    TEAM_MISSING = "team_missing"
    ISSUE_MISSING = "issue_missing"
    NO_TAGGER = "no_tagger"
    NO_EXCEPTION = "no_exception"


@frozen
class TaggerRun:
    source: ErrorTrackingIssueTag.Source
    error: Exception | None = None


def run_issue_taggers(
    team_id: int, issue_id: UUID | str, load_event_properties: Callable[[Team], dict[str, object]]
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    """Run every tagger that applies to the team on the enabled tags that list it, and store the answers.

    A tagger that raises does not stop the others. Its run carries the error, and the caller decides whether to retry.
    `load_event_properties` runs only when a tagger applies, so a team without one reads no event.
    """
    if not issue_tags_enabled(team_id):
        return IssueTaggingSkipReason.DISABLED
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return IssueTaggingSkipReason.TEAM_MISSING
    taggers = _applicable_taggers(team_id)
    if not taggers:
        return IssueTaggingSkipReason.NO_TAGGER

    try:
        issue = ErrorTrackingIssue.objects.get(team_id=team_id, id=issue_id)
        event_properties = load_event_properties(team)
        stacktrace = render_stacktrace(event_properties, TAG_STATE_MAX_TOKENS)
        if not stacktrace:
            return IssueTaggingSkipReason.NO_EXCEPTION
        context = TagContext(issue=issue, state=build_severity_state(stacktrace, event_properties))
        return tuple(_run_tagger(context, tagger, definitions) for tagger, definitions in taggers)
    except ErrorTrackingIssue.DoesNotExist:
        # The writer raises this too when a merge removes the issue while a tagger runs.
        return IssueTaggingSkipReason.ISSUE_MISSING


def _applicable_taggers(team_id: int) -> list[tuple[Tagger, tuple[IssueTagDefinition, ...]]]:
    # The caller checked ISSUE_TAGS_FLAG already, so only a tag with its own rollout flag costs another evaluation.
    rollout_flags = {definition.enabled_flag for definition in registry.ISSUE_TAG_DEFINITIONS} - {ISSUE_TAGS_FLAG}
    flag_on = {flag: team_flag_enabled(flag, team_id) for flag in rollout_flags} | {ISSUE_TAGS_FLAG: True}
    enabled = [definition for definition in registry.ISSUE_TAG_DEFINITIONS if flag_on[definition.enabled_flag]]
    applicable = []
    for tagger in TAGGERS:
        definitions = tuple(
            definition for definition in enabled if any(config.source == tagger.source for config in definition.taggers)
        )
        if definitions and tagger.applies(team_id):
            applicable.append((tagger, definitions))
    return applicable


def _run_tagger(context: TagContext, tagger: Tagger, definitions: tuple[IssueTagDefinition, ...]) -> TaggerRun:
    try:
        answers = tagger.answer(context, definitions)
        stored = tuple(
            key
            for key, answer in answers.items()
            if set_issue_tag(context.issue.team_id, context.issue.id, key, answer, tagger.source)
        )
    except ErrorTrackingIssue.DoesNotExist:
        raise
    except Exception as error:
        return TaggerRun(source=tagger.source, error=error)
    logger.info(
        "error_tracking_issue_tagged",
        team_id=context.issue.team_id,
        issue_id=str(context.issue.id),
        tagger=tagger.source,
        answered=sorted(answers),
        stored=list(stored),
    )
    return TaggerRun(source=tagger.source)
