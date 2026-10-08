import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'

import { buildFunnelTrendsActorsQuery } from './funnelTrendsTableUtils'

const source: FunnelsQuery = {
    kind: NodeKind.FunnelsQuery,
    series: [],
}

describe('buildFunnelTrendsActorsQuery', () => {
    it('scopes a previous-period click to the previous window', () => {
        const query = buildFunnelTrendsActorsQuery({
            source,
            entrancePeriodStart: '2026-06-08 00:00:00',
            compare: 'previous',
        })

        expect(query.compare).toEqual('previous')
        expect(query.funnelTrendsEntrancePeriodStart).toEqual('2026-06-08 00:00:00')
        expect(query.funnelTrendsDropOff).toBe(false)
        expect(query.includeRecordings).toBe(true)
    })

    it('passes current explicitly when clicking a current-period row', () => {
        const query = buildFunnelTrendsActorsQuery({
            source,
            entrancePeriodStart: '2026-06-15 00:00:00',
            compare: 'current',
        })

        expect(query.compare).toEqual('current')
    })

    it('omits compare outside compare mode', () => {
        const query = buildFunnelTrendsActorsQuery({
            source,
            entrancePeriodStart: '2026-06-15 00:00:00',
        })

        expect(query.compare).toBeUndefined()
    })

    it('threads a breakdown value through and omits it when absent', () => {
        const withBreakdown = buildFunnelTrendsActorsQuery({
            source,
            entrancePeriodStart: '2026-06-15 00:00:00',
            breakdownValue: 'Chrome',
        })
        const withoutBreakdown = buildFunnelTrendsActorsQuery({
            source,
            entrancePeriodStart: '2026-06-15 00:00:00',
        })

        expect(withBreakdown.funnelStepBreakdown).toEqual('Chrome')
        expect(withoutBreakdown.funnelStepBreakdown).toBeUndefined()
    })
})
