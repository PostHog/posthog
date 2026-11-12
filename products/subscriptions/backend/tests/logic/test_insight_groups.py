from products.dashboards.backend.facade.contracts import DashboardInsightTileSummary, DashboardTileGroupSummary
from products.subscriptions.backend.logic.insight_groups import group_headings_by_asset_id, section_by_tile_group


def _tile(tile_id: int, group_key: str | None) -> DashboardInsightTileSummary:
    return DashboardInsightTileSummary(
        id=tile_id, dashboard_id=1, insight_id=tile_id, layouts={}, filters_overrides=None, group_key=group_key
    )


def _outline(pairs: list[tuple[DashboardInsightTileSummary, str]], groups: list[DashboardTileGroupSummary]):
    return [
        (section.heading, [name for _tile, name in section.items]) for section in section_by_tile_group(pairs, groups)
    ]


def test_sections_follow_dashboard_group_order_with_ungrouped_first() -> None:
    groups = [
        DashboardTileGroupSummary(key="b", title="", tile_count=1),
        DashboardTileGroupSummary(key="a", title="Revenue", tile_count=4),
    ]
    pairs = [
        (_tile(1, "a"), "MRR"),
        (_tile(2, None), "Top"),
        (_tile(3, "b"), "Signups"),
        # Moved into a group after the group list was read, so it has no heading to show.
        (_tile(4, "gone"), "Stray"),
    ]

    assert _outline(pairs, groups) == [(None, ["Top", "Stray"]), ("1 tile", ["Signups"]), ("Revenue", ["MRR"])]


def test_heading_moves_to_the_next_asset_when_the_first_is_missing() -> None:
    # The group's first chart was cleaned up before delivery.
    stored = [{"heading": "Revenue", "exported_asset_ids": [2, 3]}]

    assert group_headings_by_asset_id(stored, [3]) == {3: "Revenue"}
