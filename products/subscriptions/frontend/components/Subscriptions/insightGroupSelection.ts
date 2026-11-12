import type { DashboardTile, TileGroupDisplay } from '~/types'

import {
    getDashboardSections,
    getDashboardTabs,
    getTileGroupLabel,
} from 'products/dashboards/frontend/dashboardTileSections'
import type { DashboardTileGroupApi } from 'products/dashboards/frontend/generated/api.schemas'

export interface InsightGroup {
    key: string
    label: string
    tiles: DashboardTile[]
    insightIds: number[]
}

export interface InsightGroupCheckboxState {
    checked: boolean | 'indeterminate'
    disabledReason: string | null
}

function isVisibleInsightTile(tile: DashboardTile): boolean {
    return !!tile.insight && !tile.deleted && !tile.insight.deleted
}

/**
 * Splits a dashboard's insights into its tabs or groups, in the order the dashboard shows them.
 * Returns no groups when no insight belongs to a group, so the picker shows a plain list.
 */
export function getInsightGroups({
    tiles,
    groups,
    groupDisplay,
}: {
    tiles: DashboardTile[]
    groups: Record<string, DashboardTileGroupApi> | undefined
    groupDisplay: TileGroupDisplay | undefined
}): InsightGroup[] {
    const visibleTiles = tiles.filter((tile) => !tile.deleted)
    if (!visibleTiles.some((tile) => tile.group_key && isVisibleInsightTile(tile))) {
        return []
    }
    const layout: Parameters<typeof getDashboardSections>[0]['layout'] = visibleTiles
        .filter((tile) => tile.layouts?.sm)
        .map((tile) => ({ ...tile.layouts!.sm!, i: tile.id.toString() }))
    // Tiles outside any group gather into one list, as the dashboard does for its first tab.
    const sections = getDashboardTabs(getDashboardSections({ tiles: visibleTiles, layout, groups }))

    return sections.flatMap((section): InsightGroup[] => {
        const insightTiles = section.tiles.filter(isVisibleInsightTile)
        if (!insightTiles.length) {
            return []
        }
        const label =
            section.kind === 'group'
                ? getTileGroupLabel(section.group, section.tiles.length)
                : groupDisplay === 'tabs'
                  ? 'Overview'
                  : 'Not in a group'
        return [{ key: section.key, label, tiles: insightTiles, insightIds: insightTiles.map((t) => t.insight!.id) }]
    })
}

export function getInsightGroupCheckboxState({
    group,
    validSelectedIds,
    maxInsights,
    groupDisplay,
}: {
    group: InsightGroup
    validSelectedIds: number[]
    maxInsights: number
    groupDisplay: TileGroupDisplay | undefined
}): InsightGroupCheckboxState {
    const selected = new Set(validSelectedIds)
    const selectedInGroup = group.insightIds.filter((id) => selected.has(id)).length
    const checked = selectedInGroup === 0 ? false : selectedInGroup === group.insightIds.length ? true : 'indeterminate'
    const missingCount = group.insightIds.length - selectedInGroup
    const overLimit = checked !== true && validSelectedIds.length + missingCount > maxInsights
    const noun = groupDisplay === 'tabs' ? 'tab' : 'group'
    return {
        checked,
        disabledReason: overLimit
            ? `Selecting this ${noun} would go over the limit of ${maxInsights} insights. Deselect some insights first.`
            : null,
    }
}

/** Deselects the whole group when it is fully selected, and otherwise adds the group's missing insights. */
export function toggleInsightGroup({
    group,
    selectedInsightIds,
    validSelectedIds,
}: {
    group: InsightGroup
    selectedInsightIds: number[]
    validSelectedIds: number[]
}): number[] {
    const groupIds = new Set(group.insightIds)
    const selected = new Set(validSelectedIds)
    if (group.insightIds.every((id) => selected.has(id))) {
        return selectedInsightIds.filter((id) => !groupIds.has(id))
    }
    return [...selectedInsightIds, ...group.insightIds.filter((id) => !selected.has(id))]
}
