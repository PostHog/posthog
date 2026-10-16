"""The columns a grouped logs alert may split on.

Kept apart from the query layer, because the platform wording imports it from `ready()`.
"""

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
