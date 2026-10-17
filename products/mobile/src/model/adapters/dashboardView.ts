import type { DashboardApi, DashboardTileApi } from '@/api/dashboards'
import { asRecord } from '@/lib/records'

import type { DashboardTileView, DashboardView, SavedRange } from '../views'
import {
    capabilitiesOf,
    hasGoodResult,
    ignoresRangeOverride,
    kindLabelOf,
    tileShapeOf,
    usesOwnRange,
} from './insightSnapshot'
import { sqlTableView } from './sqlVisualization'

type Layout = { x?: number; y?: number } | undefined

function position(layout: Layout): [number, number] | null {
    return typeof layout?.y === 'number' ? [layout.y, layout.x ?? 0] : null
}

/** The web's one-column order: the `xs` layout when every tile has one, else the `sm` grid read row by row. */
export function phoneTileOrder<T extends Pick<DashboardTileApi, 'layouts'>>(tiles: readonly T[]): T[] {
    for (const size of ['xs', 'sm'] as const) {
        const keyed = tiles.map((tile, index) => ({ tile, index, at: position(tile.layouts?.[size]) }))
        if (keyed.every((entry) => entry.at !== null)) {
            return keyed
                .sort((a, b) => {
                    const [ay, ax] = a.at as [number, number]
                    const [by, bx] = b.at as [number, number]
                    return ay - by || ax - bx || a.index - b.index
                })
                .map((entry) => entry.tile)
        }
    }
    return [...tiles]
}

function isVisibleTile(tile: DashboardTileApi): boolean {
    if (tile.deleted) {
        return false
    }
    if (tile.insight) {
        return !tile.insight.deleted
    }
    return Boolean(tile.text?.body)
}

function tileView(tile: DashboardTileApi): DashboardTileView {
    const insight = tile.insight
    if (!insight) {
        return {
            tileId: tile.id,
            kind: 'text',
            insightId: null,
            shortId: null,
            name: '',
            text: tile.text?.body ?? null,
            usesOwnRange: false,
            ignoresRangeOverride: false,
            capabilities: { number: false, chart: false, people: false },
            kindLabel: 'Text',
            seriesCount: 0,
            hasBreakdown: false,
        }
    }
    const sqlTable = hasGoodResult(insight) ? sqlTableView(insight.query, insight) : null
    return {
        tileId: tile.id,
        kind: 'insight',
        insightId: insight.id,
        shortId: insight.short_id,
        name: insight.name || insight.derived_name || 'Untitled',
        text: null,
        usesOwnRange: usesOwnRange(tile.filters_overrides, insight.query),
        ignoresRangeOverride: ignoresRangeOverride(insight.query),
        capabilities: capabilitiesOf(insight.query, insight.result, sqlTable),
        kindLabel: kindLabelOf(insight.query, sqlTable),
        ...tileShapeOf(insight.query),
    }
}

export function dashboardSavedRange(filters: Record<string, unknown> | null | undefined): SavedRange {
    const record = asRecord(filters)
    return {
        dateFrom: typeof record?.date_from === 'string' ? record.date_from : null,
        dateTo: typeof record?.date_to === 'string' ? record.date_to : null,
    }
}

/** The tiles the phone shows, in phone order: insight tiles and text cards. Button and widget tiles are left out. */
export function phoneTiles(api: DashboardApi): DashboardTileApi[] {
    return phoneTileOrder((api.tiles ?? []).filter(isVisibleTile))
}

export function dashboardView(api: DashboardApi): DashboardView {
    return {
        id: api.id,
        name: api.name || 'Untitled',
        description: api.description || null,
        // `filters` carries the request's override, so only `persisted_filters` gives the saved range on such a read.
        savedRange: dashboardSavedRange('persisted_filters' in api ? api.persisted_filters : api.filters),
        lastRefresh: api.last_refresh ?? null,
        tiles: phoneTiles(api).map(tileView),
    }
}
