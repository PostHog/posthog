from collections.abc import Collection, Iterable
from uuid import UUID

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.models import ErrorTrackingIssueTag


def tags_by_issue(
    team_id: int, issue_ids: Collection[UUID | str], definitions: Collection[IssueTagDefinition]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]]:
    """The answers of each issue to the given tags, read from Postgres in one query."""
    rows = ErrorTrackingIssueTag.objects.for_team(team_id).filter(
        issue_id__in=issue_ids, key__in=[definition.key for definition in definitions]
    )
    return group_issue_tags(rows.values_list("issue_id", "key", "value", "source"), definitions)


def group_issue_tags(
    rows: Iterable[tuple[UUID | str, str, bool | None, str | None]], definitions: Collection[IssueTagDefinition]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]]:
    """The answers of each issue, keyed by issue id and sorted by tag key. An issue without answers has no key.

    Each row is an issue id, a tag key from `definitions`, the answer and its source.
    """
    definitions_by_key = {definition.key: definition for definition in definitions}
    result: dict[str, list[contracts.ErrorTrackingIssueTag]] = {}
    for issue_id, key, value, source in sorted(rows, key=lambda row: row[1]):
        definition = definitions_by_key[key]
        result.setdefault(str(issue_id), []).append(
            contracts.ErrorTrackingIssueTag(
                key=key, label=definition.label, description=definition.description, value=value, source=source
            )
        )
    return result
