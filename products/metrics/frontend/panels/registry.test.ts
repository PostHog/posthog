import { METRICS_PANELS, resolvePanelType, resolveReducer, statSummaryToReduce } from './registry'

describe('resolvePanelType', () => {
    it('defaults to line when no display is set', () => {
        expect(resolvePanelType(undefined)).toBe('line')
        expect(resolvePanelType({})).toBe('line')
    })

    it('passes through a known type', () => {
        expect(resolvePanelType({ type: 'stat' })).toBe('stat')
        expect(resolvePanelType({ type: 'table' })).toBe('table')
        expect(resolvePanelType({ type: 'heatmap' })).toBe('heatmap')
    })

    it('falls back to line for an unknown type', () => {
        expect(resolvePanelType({ type: 'pie' as never })).toBe('line')
    })

    it('has a definition for every display type', () => {
        for (const type of ['line', 'area', 'bar', 'stat', 'gauge', 'bargauge', 'table', 'heatmap'] as const) {
            expect(METRICS_PANELS[type]).toBeDefined()
            expect(METRICS_PANELS[type].label).toBeTruthy()
        }
    })

    it('marks group-by-only panels', () => {
        expect(METRICS_PANELS.bargauge.needsGroupBy).toBe(true)
        expect(METRICS_PANELS.stat.needsGroupBy).toBeUndefined()
    })

    it('marks the histogram-only panel', () => {
        expect(METRICS_PANELS.heatmap.needsHistogram).toBe(true)
    })
})

describe('statSummaryToReduce', () => {
    it('maps the deprecated values', () => {
        expect(statSummaryToReduce('latest')).toBe('last')
        expect(statSummaryToReduce('average')).toBe('mean')
        expect(statSummaryToReduce('total')).toBe('sum')
    })

    it('defaults to last', () => {
        expect(statSummaryToReduce(undefined)).toBe('last')
    })
})

describe('resolveReducer', () => {
    it('prefers reduce over statSummary', () => {
        expect(resolveReducer({ reduce: 'max', statSummary: 'total' })).toBe('max')
    })

    it('falls back to statSummary', () => {
        expect(resolveReducer({ statSummary: 'average' })).toBe('mean')
    })

    it('defaults to last', () => {
        expect(resolveReducer({})).toBe('last')
        expect(resolveReducer(undefined)).toBe('last')
    })
})
