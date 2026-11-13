from collections.abc import Collection, Iterable
from uuid import UUID

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.models import ErrorTrackingIssueTag


def tags_by_issue(
    team_id: int, issue_ids: Collection[UUID | str], definitions: Collection[IssueTagDefinition]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]]:
    """The tags from `definitions` that are applied to each issue, read from Postgres in one query."""
    rows = ErrorTrackingIssueTag.objects.for_team(team_id).filter(
        issue_id__in=issue_ids, key__in=[definition.key for definition in definitions], value=True
    )
    return group_issue_tags(rows.values_list("issue_id", "key", "source"), definitions)


def group_issue_tags(
    rows: Iterable[tuple[UUID | str, str, str | None]], definitions: Collection[IssueTagDefinition]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]]:
    """The applied tags of each issue, keyed by issue id and sorted by tag key. An issue without one has no key.

    Each row is an issue id, the key of a tag from `definitions` that is applied to it, and the tagger that applied it.
    """
    definitions_by_key = {definition.key: definition for definition in definitions}
    result: dict[str, list[contracts.ErrorTrackingIssueTag]] = {}
    for issue_id, key, source in sorted(rows, key=lambda row: row[1]):
        definition = definitions_by_key[key]
        result.setdefault(str(issue_id), []).append(
            contracts.ErrorTrackingIssueTag(
                key=key, label=definition.label, description=definition.description, source=source
            )
        )
    return result
