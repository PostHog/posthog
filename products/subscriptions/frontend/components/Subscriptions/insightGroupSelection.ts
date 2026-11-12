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

// Matches the fallback delivery uses in products/subscriptions/backend/temporal/activities.py, so a tile with no
// saved layout sits in the same place in the picker as in the sent report.
const MISSING_LAYOUT_POSITION = 100

function layoutPosition(tile: DashboardTile): { x: number; y: number } {
    return {
        x: tile.layouts?.sm?.x ?? MISSING_LAYOUT_POSITION,
        y: tile.layouts?.sm?.y ?? MISSING_LAYOUT_POSITION,
    }
}

export function isVisibleInsightTile(tile: DashboardTile): boolean {
    return !!tile.insight && !tile.deleted && !tile.insight.deleted
}

export function sortTilesByLayout(tiles: DashboardTile[]): DashboardTile[] {
    return [...tiles].sort((a, b) => {
        const [pa, pb] = [layoutPosition(a), layoutPosition(b)]
        return pa.y - pb.y || pa.x - pb.x
    })
}

// Returns no groups when no insight is in a group, so the picker falls back to a plain list.
export function getInsightGroups({
    tiles,
    groups,
    groupDisplay,
}: {
    tiles: DashboardTile[]
    groups?: Record<string, DashboardTileGroupApi> | null
    groupDisplay?: TileGroupDisplay | null
}): InsightGroup[] {
    const nonDeletedTiles = tiles.filter((tile) => !tile.deleted)
    if (!nonDeletedTiles.some((tile) => tile.group_key && isVisibleInsightTile(tile))) {
        return []
    }
    const layout = nonDeletedTiles.map((tile) => ({
        ...layoutPosition(tile),
        w: tile.layouts?.sm?.w ?? 1,
        h: tile.layouts?.sm?.h ?? 1,
        i: tile.id.toString(),
    }))
    // Tiles outside any group gather into one list first, so one checkbox covers them. Tabs mode shows them
    // the same way, but sections mode places them in bands between groups.
    const sections = getDashboardTabs(
        getDashboardSections({ tiles: nonDeletedTiles, layout, groups: groups ?? undefined })
    )

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

interface GroupSelectionInput {
    group: InsightGroup
    validSelectedIds: number[]
    maxInsights: number
}

function groupSelection({ group, validSelectedIds, maxInsights }: GroupSelectionInput): {
    selectedInGroup: number
    fitsUnderLimit: boolean
} {
    const selected = new Set(validSelectedIds)
    const selectedInGroup = group.insightIds.filter((id) => selected.has(id)).length
    const missingCount = group.insightIds.length - selectedInGroup
    return { selectedInGroup, fitsUnderLimit: validSelectedIds.length + missingCount <= maxInsights }
}

export function getInsightGroupCheckboxState({
    groupDisplay,
    ...input
}: GroupSelectionInput & { groupDisplay?: TileGroupDisplay | null }): InsightGroupCheckboxState {
    const { selectedInGroup, fitsUnderLimit } = groupSelection(input)
    const checked =
        selectedInGroup === 0 ? false : selectedInGroup === input.group.insightIds.length ? true : 'indeterminate'
    const noun = groupDisplay === 'tabs' ? 'tab' : 'group'
    return {
        checked,
        // A partly selected group that can't fit clears on click instead, so only an empty one is disabled.
        disabledReason:
            checked === false && !fitsUnderLimit
                ? `Selecting this ${noun} would go over the limit of ${input.maxInsights} insights. Deselect some insights first.`
                : null,
    }
}

export function toggleInsightGroup({
    selectedInsightIds,
    ...input
}: GroupSelectionInput & { selectedInsightIds: number[] }): number[] {
    const { selectedInGroup, fitsUnderLimit } = groupSelection(input)
    const { group, validSelectedIds } = input
    if (selectedInGroup === group.insightIds.length || !fitsUnderLimit) {
        const groupIds = new Set(group.insightIds)
        return selectedInsightIds.filter((id) => !groupIds.has(id))
    }
    const selected = new Set(validSelectedIds)
    return [...selectedInsightIds, ...group.insightIds.filter((id) => !selected.has(id))]
}

export function toggleInsight({
    insightId,
    selectedInsightIds,
    validSelectedIds,
    maxInsights,
}: {
    insightId: number
    selectedInsightIds: number[]
    validSelectedIds: number[]
    maxInsights: number
}): number[] {
    if (validSelectedIds.includes(insightId)) {
        return selectedInsightIds.filter((id) => id !== insightId)
    }
    return validSelectedIds.length < maxInsights ? [...selectedInsightIds, insightId] : selectedInsightIds
}
