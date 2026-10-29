import type { InsightSnapshot, PinView } from '@/model/views'

import { automaticPinCandidates, automaticPinMode, resolvePinDisplays, selectPinDisplay } from './smartPinDisplay'

const line = {
    kind: 'InsightVizNode',
    source: {
        kind: 'TrendsQuery',
        series: [{ kind: 'EventsNode', event: '$pageview' }],
        trendsFilter: { display: 'ActionsLineGraph' },
    },
}

function pin(id: number): PinView {
    return {
        kind: 'dashboard',
        ref: String(id),
        name: `Dashboard ${id}`,
        href: null,
        shortcutId: `pin-${id}`,
        shortcutIds: [`pin-${id}`],
        type: 'dashboard',
        serverOrder: id,
        rank: null,
        display: { mode: 'row' },
        native: true,
    }
}

describe('automatic pin display selection', () => {
    test.each<[unknown, 'number' | 'chart' | null]>([
        [line, 'chart'],
        [
            { kind: 'DataVisualizationNode', display: 'BoldNumber', source: { kind: 'HogQLQuery', query: 'select 1' } },
            'number',
        ],
        [{ ...line, source: { ...line.source, trendsFilter: { display: 'BoldNumber' } } }, 'number'],
        [{ ...line, source: { ...line.source, series: [...line.source.series, ...line.source.series] } }, null],
        [{ ...line, source: { ...line.source, breakdownFilter: { breakdown: '$browser' } } }, null],
        [{ kind: 'FunnelsQuery', series: [] }, null],
    ])('chooses only an unambiguous number or time series: %j', (query, mode) => {
        expect(automaticPinMode(query)).toBe(mode)
    })

    test('prefers a usable cached tile over an uncached tile without selecting misleading breakdowns', () => {
        const ready = { lastRefreshAt: '2026-10-20T12:00:00Z', refreshFailed: false, value: 0 } as InsightSnapshot
        const display = selectPinDisplay([
            { display: { tileId: 1, insightId: 1, insightShortId: 'cold' }, query: line },
            { display: { tileId: 2, insightId: 2, insightShortId: 'ready' }, query: line, snapshot: ready },
            {
                display: { tileId: 3, insightId: 3, insightShortId: 'breakdown' },
                snapshot: ready,
                query: { ...line, source: { ...line.source, breakdownFilter: { breakdown: '$browser' } } },
            },
        ])
        expect(display).toEqual({ mode: 'chart', tileId: 2, insightId: 2, insightShortId: 'ready' })
    })

    test('bounds missing-preference discovery and preserves explicit modes and actual pin identities', () => {
        const pins = Array.from({ length: 7 }, (_, index) => pin(index + 1))
        const prefs = { 'pin-1': { mode: 'row' as const }, 'pin-2': { mode: 'number' as const, insightId: 20 } }
        expect(automaticPinCandidates(pins, prefs).map((pin) => pin.shortcutId)).toEqual(['pin-3', 'pin-4', 'pin-5'])
        const resolved = resolvePinDisplays(pins, prefs, {
            'pin-1': { mode: 'chart' },
            'pin-2': { mode: 'chart' },
            'pin-3': { mode: 'chart', tileId: 3, insightId: 30 },
        })
        expect(resolved.map((pin) => pin.shortcutId)).toEqual(pins.map((pin) => pin.shortcutId))
        expect(resolved.map((pin) => pin.display.mode)).toEqual(['row', 'number', 'chart', 'row', 'row', 'row', 'row'])
        expect(resolved[2]).toEqual({ ...pins[2], display: { mode: 'chart', tileId: 3, insightId: 30 } })
        expect(pins[2]?.display.mode).toBe('row')
    })
})
