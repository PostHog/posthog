import type { DashboardTileView } from '@/model/views'

export type TileMode = 'number' | 'chart'

export interface TilesByEligibility {
    /** Tiles the pin can show in this mode, in dashboard order. */
    usable: DashboardTileView[]
    /** The rest, in dashboard order, each with the reason it is out. */
    unusable: { tile: DashboardTileView; reason: string }[]
}

/** One short reason, shown after the tile's kind: "Line · Has 3 series". */
export function tileLimitReason(tile: DashboardTileView, mode: TileMode): string {
    if (tile.kind === 'text') {
        return 'Text card'
    }
    if (mode === 'number' && tile.hasBreakdown) {
        return 'Has a breakdown'
    }
    if (mode === 'number' && tile.seriesCount > 1) {
        return `Has ${tile.seriesCount} series`
    }
    return mode === 'number' ? 'Not a single number' : 'Not a chart over time'
}

export function splitTilesByEligibility(tiles: readonly DashboardTileView[], mode: TileMode): TilesByEligibility {
    const usable: DashboardTileView[] = []
    const unusable: TilesByEligibility['unusable'] = []
    for (const tile of tiles) {
        if (tile.capabilities[mode]) {
            usable.push(tile)
        } else {
            unusable.push({ tile, reason: tileLimitReason(tile, mode) })
        }
    }
    return { usable, unusable }
}
