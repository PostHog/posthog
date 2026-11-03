import type { DashboardTileView } from '@/model/views'

import { splitTilesByEligibility, tileLimitReason } from './tileEligibility'

function tile(overrides: Partial<DashboardTileView> & { tileId: number }): DashboardTileView {
    return {
        kind: 'insight',
        insightId: overrides.tileId,
        shortId: `s${overrides.tileId}`,
        name: `Tile ${overrides.tileId}`,
        text: null,
        usesOwnRange: false,
        ignoresRangeOverride: false,
        capabilities: { number: false, chart: false, people: false },
        kindLabel: 'Line',
        seriesCount: 1,
        hasBreakdown: false,
        ...overrides,
    }
}

describe('tileEligibility', () => {
    it('lists the tiles the mode can show first and keeps dashboard order inside each group', () => {
        const tiles = [
            tile({ tileId: 1, kindLabel: 'Funnel', seriesCount: 0 }),
            tile({ tileId: 2, capabilities: { number: true, chart: true, people: true } }),
            tile({ tileId: 3, seriesCount: 3 }),
            tile({ tileId: 4, kindLabel: 'Big number', capabilities: { number: true, chart: false, people: false } }),
        ]
        const { usable, unusable } = splitTilesByEligibility(tiles, 'number')
        expect(usable.map((entry) => entry.tileId)).toEqual([2, 4])
        expect(unusable.map((entry) => [entry.tile.tileId, entry.reason])).toEqual([
            [1, 'Not a single number'],
            [3, 'Has 3 series'],
        ])
        expect(splitTilesByEligibility(tiles, 'chart').usable.map((entry) => entry.tileId)).toEqual([2])
    })

    it.each<[Partial<DashboardTileView>, 'number' | 'chart', string]>([
        [{ kind: 'text', kindLabel: 'Text', seriesCount: 0 }, 'number', 'Text card'],
        [{ hasBreakdown: true, seriesCount: 2 }, 'number', 'Has a breakdown'],
        [{ seriesCount: 2 }, 'number', 'Has 2 series'],
        [{ kindLabel: 'Pie' }, 'chart', 'Not a chart over time'],
    ])('names the reason for %o in %s mode', (overrides, mode, reason) => {
        expect(tileLimitReason(tile({ tileId: 9, ...overrides }), mode)).toBe(reason)
    })
})
