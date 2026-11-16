from collections.abc import Callable, Collection
from enum import StrEnum
from uuid import UUID

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.error_tracking.backend.logic.issue_tags.enabled import issue_tag_definitions_for_enabled_team
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagContext, Tagger
from products.error_tracking.backend.logic.issue_tags.taggers.jev import JevTagger
from products.error_tracking.backend.logic.issue_tags.taggers.rule import RuleTagger
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag

logger = structlog.get_logger(__name__)

TAGGERS: tuple[Tagger, ...] = (RuleTagger(), JevTagger())


class IssueTaggingSkipReason(StrEnum):
    DISABLED = "disabled"
    TEAM_MISSING = "team_missing"
    ISSUE_MISSING = "issue_missing"
    NO_TAGGER = "no_tagger"


@frozen
class TaggerRun:
    source: ErrorTrackingIssueTag.Source
    error: Exception | None = None


def run_issue_taggers(
    team_id: int,
    issue_id: UUID | str,
    load_event_properties: Callable[[Team], dict[str, object]],
    *,
    taggers: tuple[Tagger, ...] | None = None,
    keys: Collection[str] | None = None,
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    """Run every tagger that applies to the team on the enabled tags that list it, and store the answers.

    `taggers` (default `TAGGERS`) and `keys` (default every enabled tag) limit what runs, for a re-run.
    A tagger that raises does not stop the others. Its run carries the error, and the caller decides whether to retry.
    `load_event_properties` runs only when a tagger applies, so a team without one reads no event.
    """
    return _run_issue_taggers(
        team_id, TAGGERS if taggers is None else taggers, Q(id=issue_id), load_event_properties, keys=keys
    )


def run_rule_tagger_on_merge_target(
    team_id: int, fingerprint: str, load_event_properties: Callable[[Team], dict[str, object]]
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    """Run the rules on an exception that merged into an existing issue at creation, and label that issue.

    The merge moved the fingerprint onto the target issue, so the fingerprint finds it. Jev does not run, because Jev
    answers from an issue's first event and the target issue has its own. A team without rules reads no issue and no
    event.
    """
    rule_taggers = tuple(tagger for tagger in TAGGERS if tagger.source == ErrorTrackingIssueTag.Source.RULE)
    issue = Q(fingerprints__team_id=team_id, fingerprints__fingerprint=fingerprint)
    return _run_issue_taggers(team_id, rule_taggers, issue, load_event_properties)


def _run_issue_taggers(
    team_id: int,
    taggers: tuple[Tagger, ...],
    issue_filter: Q,
    load_event_properties: Callable[[Team], dict[str, object]],
    *,
    keys: Collection[str] | None = None,
) -> tuple[TaggerRun, ...] | IssueTaggingSkipReason:
    if not issue_tags_enabled(team_id):
        return IssueTaggingSkipReason.DISABLED
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return IssueTaggingSkipReason.TEAM_MISSING
    applicable = applicable_taggers(team_id, taggers, keys)
    if not applicable:
        return IssueTaggingSkipReason.NO_TAGGER

    try:
        issue = ErrorTrackingIssue.objects.get(issue_filter, team_id=team_id)
        context = TagContext(issue=issue, event_properties=load_event_properties(team))
        return tuple(_run_tagger(context, tagger, definitions) for tagger, definitions in applicable)
    except ErrorTrackingIssue.DoesNotExist:
        # The writer raises this too when a merge removes the issue while a tagger runs.
        return IssueTaggingSkipReason.ISSUE_MISSING


def applicable_taggers(
    team_id: int, taggers: tuple[Tagger, ...], keys: Collection[str] | None
) -> list[tuple[Tagger, tuple[IssueTagDefinition, ...]]]:
    """Each tagger that applies to the team, with the enabled tags that list it. The caller checked ISSUE_TAGS_FLAG."""
    enabled = issue_tag_definitions_for_enabled_team(team_id)
    if keys is not None:
        enabled = tuple(definition for definition in enabled if definition.key in keys)
    applicable = []
    for tagger in taggers:
        definitions = tuple(
            definition for definition in enabled if any(config.source == tagger.source for config in definition.taggers)
        )
        if definitions and tagger.applies(team_id):
            applicable.append((tagger, definitions))
    return applicable


def _run_tagger(context: TagContext, tagger: Tagger, definitions: tuple[IssueTagDefinition, ...]) -> TaggerRun:
    try:
        answers = tagger.answer(context, definitions)
        by_key = {definition.key: definition for definition in definitions}
        stored = tuple(
            key
            for key, answer in answers.items()
            if set_issue_tag(context.issue.team_id, context.issue.id, by_key[key], answer, tagger.source)
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
