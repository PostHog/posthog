"""The columns a grouped logs alert may split on.

Kept apart from the query layer, because the platform wording imports it from `ready()`.
"""

from collections.abc import Sequence
from typing import Final

from posthog.dataclasses import frozen


@frozen
class GroupColumn:
    # The name a reader knows the column by.
    label: str
    # The logs scene filter that narrows a link to one group.
    filter_key: str
    # The `log` property filter key a `filterGroup` selects this column under.
    filter_group_key: str


# Both are low-cardinality columns of the logs table, and `service_name` leads its primary key, so
# grouping on them stays cheap.
GROUP_COLUMNS: Final[dict[str, GroupColumn]] = {
    "service_name": GroupColumn(label="Service", filter_key="serviceNames", filter_group_key="service_name"),
    "severity_text": GroupColumn(label="Severity", filter_key="severityLevels", filter_group_key="severity_level"),
}


def grouping_problem(keys: Sequence[str], threshold_operator: object) -> str | None:
    """Why a logs alert grouped by `keys` cannot be evaluated, or None when it can."""
    if unknown := set(keys) - GROUP_COLUMNS.keys():
        return f"A logs alert can only group by {', '.join(sorted(GROUP_COLUMNS))}, not {', '.join(sorted(unknown))}."
    # A group with no matching log returns no row, so a service gone silent, the case a `below`
    # alert exists for, is never seen unless it was already open.
    if threshold_operator != "above":
        return "A grouped logs alert can only alert above a threshold."
    return None
