import type {
    TransactionalEmailStatsCountsApi,
    TransactionalEmailStatsOverTimeApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { buildMetricTiles } from './emailMetricTiles'

function counts(sent: number, bounced = 0): TransactionalEmailStatsCountsApi {
    return { sent, delivered: sent - bounced, bounced, complained: 0, failed: 0 }
}

function stats(
    buckets: TransactionalEmailStatsCountsApi[],
    previous: TransactionalEmailStatsCountsApi | null
): TransactionalEmailStatsOverTimeApi {
    return {
        interval: 'day',
        timezone: 'UTC',
        buckets: buckets.map((bucket, index) => ({ start: `2026-06-0${index + 1}T00:00:00Z`, counts: bucket })),
        previous,
    }
}

describe('emailMetricTiles', () => {
    it('does not plot a day without sends as a 0% rate', () => {
        const delivered = buildMetricTiles(stats([counts(0), counts(100, 10), counts(0), counts(50)], null))[1]
        expect(delivered.points).toEqual([90, 90, 90, 100])
    })

    it.each([
        { name: 'compares a count in percent', previous: counts(100, 5), tile: 0, expected: 100 },
        { name: 'compares a rate in percentage points', previous: counts(100, 5), tile: 2, expected: 5 },
        { name: 'has no comparison without an earlier period', previous: null, tile: 2, expected: null },
        {
            name: 'has no comparison when the earlier period sent nothing',
            previous: counts(0),
            tile: 0,
            expected: null,
        },
    ])('$name', ({ previous, tile, expected }) => {
        expect(buildMetricTiles(stats([counts(200, 20)], previous))[tile].change).toEqual(expected)
    })

    it('shows no rate when nothing was sent', () => {
        expect(buildMetricTiles(stats([counts(0)], null))[1].value).toBeNull()
    })
})
