from collections.abc import Collection
from uuid import UUID

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.models import ErrorTrackingIssueTag


def tags_by_issue(
    team_id: int, issue_ids: Collection[UUID | str], definitions: Collection[IssueTagDefinition]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]]:
    """The answers of each issue to the given tags, read in one query and keyed by issue id.

    An issue without answers has no key.
    """
    definitions_by_key = {definition.key: definition for definition in definitions}
    rows = ErrorTrackingIssueTag.objects.for_team(team_id).filter(issue_id__in=issue_ids, key__in=definitions_by_key)
    result: dict[str, list[contracts.ErrorTrackingIssueTag]] = {}
    for issue_id, key, value, source in rows.order_by("key").values_list("issue_id", "key", "value", "source"):
        definition = definitions_by_key[key]
        result.setdefault(str(issue_id), []).append(
            contracts.ErrorTrackingIssueTag(
                key=key, label=definition.label, description=definition.description, value=value, source=source
            )
        )
    return result
