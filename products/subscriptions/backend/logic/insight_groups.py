"""Order a dashboard report's insights by the dashboard's tile groups, and head each group.

The order mirrors the subscription picker and the dashboard (`getDashboardSections` and `getDashboardTabs`
in `products/dashboards/frontend/dashboardTileSections.ts`): insights outside any group come first, then
each group in the order the dashboard shows it. Within a section, insights keep their layout order.
"""

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.dashboards.backend.facade.contracts import DashboardInsightTileSummary, DashboardTileGroupSummary

TILE_GROUP_SECTIONS_FEATURE_FLAG_KEY = "dashboard-tile-group-sections"

# The content_snapshot key that carries the sections from export to delivery. A delivery row without it
# (no groups, flag off, or written by a worker from before this key) renders as one flat list.
INSIGHT_GROUPS_SNAPSHOT_KEY = "insight_groups"

T = TypeVar("T")


@frozen
class InsightSection:
    """Consecutive insights of a report under one heading. `heading` is None for insights outside any group."""

    heading: str | None
    items: list[Any]


def tile_group_sections_enabled(*, organization_id: str, distinct_id: str | None) -> bool:
    if not distinct_id:
        return False
    with posthoganalytics.new_context(capture_exceptions=False):
        posthoganalytics.tag("$update_person_last_seen_at", False)
        return feature_enabled_or_false(
            TILE_GROUP_SECTIONS_FEATURE_FLAG_KEY,
            distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
        )


def section_by_tile_group(
    pairs: Sequence[tuple[DashboardInsightTileSummary | None, T]],
    groups: Sequence[DashboardTileGroupSummary],
) -> list[InsightSection]:
    """Split pairs already in layout order into sections. Returns [] when no pair sits in a known group."""
    group_order = {group.key: index for index, group in enumerate(groups)}
    ungrouped: list[tuple[DashboardInsightTileSummary | None, T]] = []
    grouped: dict[str, list[tuple[DashboardInsightTileSummary | None, T]]] = {}
    for pair in pairs:
        tile = pair[0]
        group_key = tile.group_key if tile is not None else None
        # A group key the group list does not know about can only come from a tile moved between the two
        # reads, so it counts as ungrouped rather than getting a heading nobody chose.
        if group_key and group_key in group_order:
            grouped.setdefault(group_key, []).append(pair)
        else:
            ungrouped.append(pair)

    if not grouped:
        return []

    sections: list[InsightSection] = []
    if ungrouped:
        sections.append(InsightSection(heading=None, items=ungrouped))
    for group in groups:
        if group.key in grouped:
            sections.append(InsightSection(heading=group.heading, items=grouped[group.key]))
    return sections


def snapshot_sections(sections: Sequence[InsightSection], asset_ids: Sequence[Sequence[int]]) -> list[dict[str, Any]]:
    """The JSON stored on the delivery row: each section's heading and the ids of its exported assets."""
    return [
        {"heading": section.heading, "exported_asset_ids": list(ids)}
        for section, ids in zip(sections, asset_ids, strict=True)
    ]


def group_headings_by_asset_id(snapshot: Any, present_asset_ids: Sequence[int]) -> dict[int, str]:
    """The heading to show before each asset that opens a section, read from the stored sections.

    An asset that failed to load is skipped, so its heading moves to the next asset in the same section.
    Anything malformed yields no headings, which renders the report as one flat list.
    """
    if not isinstance(snapshot, list):
        return {}
    present = set(present_asset_ids)
    headings: dict[int, str] = {}
    for section in snapshot:
        if not isinstance(section, Mapping):
            return {}
        heading = section.get("heading")
        ids = section.get("exported_asset_ids")
        if not isinstance(ids, list):
            return {}
        if not isinstance(heading, str) or not heading:
            continue
        first_present = next((asset_id for asset_id in ids if asset_id in present), None)
        if first_present is not None:
            headings[first_present] = heading
    return headings
