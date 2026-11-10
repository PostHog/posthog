from collections.abc import Collection
from uuid import UUID

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_tags.gate import enabled_issue_tag_definitions
from products.error_tracking.backend.models import ErrorTrackingIssueTag


def tags_by_issue(
    team_id: int, issue_ids: Collection[UUID | str]
) -> dict[str, list[contracts.ErrorTrackingIssueTag]] | None:
    """The enabled tags of each issue, read in one query and keyed by issue id. An issue without tags has no key.

    Return None when the team has no enabled tag, which includes while issue tags are off for the team.
    """
    definitions_by_key = {definition.key: definition for definition in enabled_issue_tag_definitions(team_id)}
    if not definitions_by_key:
        return None
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
