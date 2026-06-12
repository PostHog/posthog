import { describe, expect, it } from 'vitest'

import { type InsightActorsData, toActorRows } from 'products/product_analytics/mcp/apps/insightActorsTransforms'

function actorsData(columns: string[], rows: (string | number | null | string[])[][]): InsightActorsData {
    return {
        query: { kind: 'InsightActorsQuery' },
        results: { columns, results: rows },
        hasMore: false,
        offset: 0,
    }
}

describe('toActorRows', () => {
    it('maps rows onto named columns', () => {
        const data = actorsData(
            ['distinct_id', 'email', 'name', 'event_count', 'recordings'],
            [
                ['abc-123', 'max@posthog.com', 'Max', 42, ['https://us.posthog.com/replay/1']],
                ['def-456', null, null, 7, []],
            ]
        )
        expect(toActorRows(data)).toEqual([
            {
                distinct_id: 'abc-123',
                email: 'max@posthog.com',
                name: 'Max',
                event_count: 42,
                recordings: ['https://us.posthog.com/replay/1'],
            },
            { distinct_id: 'def-456', email: null, name: null, event_count: 7, recordings: [] },
        ])
    })

    it('is independent of column order', () => {
        const data = actorsData(['event_count', 'distinct_id'], [[42, 'abc-123']])
        expect(toActorRows(data)).toEqual([
            { distinct_id: 'abc-123', email: null, name: null, event_count: 42, recordings: [] },
        ])
    })

    it('nulls out missing columns and ignores unknown ones', () => {
        const data = actorsData(['distinct_id', 'favorite_color'], [['abc-123', 'orange']])
        expect(toActorRows(data)).toEqual([
            { distinct_id: 'abc-123', email: null, name: null, event_count: null, recordings: [] },
        ])
    })

    it('treats a non-array recordings value as no recordings', () => {
        const data = actorsData(['distinct_id', 'recordings'], [['abc-123', 'not-a-list']])
        expect(toActorRows(data)[0]?.recordings).toEqual([])
    })

    it('returns an empty array when there are no rows', () => {
        expect(toActorRows(actorsData(['distinct_id'], []))).toEqual([])
    })
})
