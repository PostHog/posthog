"""Order a dashboard report's insights by the dashboard's tile groups, and head each group.

The order mirrors the subscription picker and the dashboard (`getDashboardSections` and `getDashboardTabs`
in `products/dashboards/frontend/dashboardTileSections.ts`): insights outside any group come first, then
each group in the order the dashboard shows it. Within a section, insights keep their layout order.
"""

from collections.abc import Mapping, Sequence
from itertools import groupby
from operator import itemgetter
from typing import Any

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.dashboards.backend.facade.contracts import DashboardInsightTileSummary, DashboardTileGroupSummary

TILE_GROUP_SECTIONS_FEATURE_FLAG_KEY = "dashboard-tile-group-sections"

# The content_snapshot key that carries the sections from export to delivery. A delivery row without it
# (no groups, flag off, or written by a worker from before this key) renders as one flat list.
SECTIONS_SNAPSHOT_KEY = "insight_sections"

# The heading to show before an exported asset, keyed by the asset's id.
GroupHeadings = Mapping[int, str]


@frozen
class InsightSection[T]:
    """Consecutive insights of a report under one heading. `heading` is None for insights outside any group."""

    heading: str | None
    items: list[tuple[DashboardInsightTileSummary | None, T]]


@frozen
class StoredSection:
    heading: str | None
    exported_asset_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"heading": self.heading, "exported_asset_ids": list(self.exported_asset_ids)}

    @classmethod
    def parse_list(cls, raw: Any) -> list["StoredSection"]:
        """Anything malformed parses as no sections, which renders the report as one flat list."""
        if not isinstance(raw, list):
            return []
        sections: list[StoredSection] = []
        for item in raw:
            if not isinstance(item, Mapping):
                return []
            heading, ids = item.get("heading"), item.get("exported_asset_ids")
            if not isinstance(ids, list) or not all(isinstance(asset_id, int) for asset_id in ids):
                return []
            sections.append(
                cls(heading=heading if isinstance(heading, str) and heading else None, exported_asset_ids=tuple(ids))
            )
        return sections


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


def section_by_tile_group[T](
    pairs: Sequence[tuple[DashboardInsightTileSummary | None, T]],
    groups: Sequence[DashboardTileGroupSummary],
) -> list[InsightSection[T]]:
    """Split pairs already in layout order into sections. Returns [] when no pair sits in a known group."""
    known_group_keys = {group.key for group in groups}
    ungrouped: list[tuple[DashboardInsightTileSummary | None, T]] = []
    grouped: dict[str, list[tuple[DashboardInsightTileSummary | None, T]]] = {}
    for pair in pairs:
        tile = pair[0]
        group_key = tile.group_key if tile is not None else None
        # A group key the group list does not know about can only come from a tile moved between the two
        # reads, so it counts as ungrouped rather than getting a heading nobody chose.
        if group_key and group_key in known_group_keys:
            grouped.setdefault(group_key, []).append(pair)
        else:
            ungrouped.append(pair)

    if not grouped:
        return []

    sections: list[InsightSection[T]] = []
    if ungrouped:
        sections.append(InsightSection(heading=None, items=ungrouped))
    for group in groups:
        if group.key in grouped:
            sections.append(InsightSection(heading=group.heading, items=grouped[group.key]))
    return sections


def stored_sections(
    sections: Sequence[InsightSection[Any]], section_indexes: Sequence[int], asset_ids: Sequence[int]
) -> list[StoredSection]:
    """Group the exported assets by the section each came from. A section the export limit cut off is left out."""
    # Grouped by index, not heading, because two groups can share a heading such as "2 tiles".
    return [
        StoredSection(heading=sections[index].heading, exported_asset_ids=tuple(asset_id for _, asset_id in run))
        for index, run in groupby(zip(section_indexes, asset_ids, strict=True), key=itemgetter(0))
    ]


def group_headings_by_asset_id(sections: Sequence[StoredSection], present_asset_ids: Sequence[int]) -> dict[int, str]:
    """The heading to show before each asset that opens a section.

    An asset that failed to load is skipped, so its heading moves to the next asset in the same section.
    """
    present = set(present_asset_ids)
    headings: dict[int, str] = {}
    for section in sections:
        if section.heading is None:
            continue
        first_present = next((asset_id for asset_id in section.exported_asset_ids if asset_id in present), None)
        if first_present is not None:
            headings[first_present] = section.heading
    return headings
