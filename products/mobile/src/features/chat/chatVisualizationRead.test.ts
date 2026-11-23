import { type InsightApi, readInsight } from '@/api/insights'
import { recordServerDate, resetServerClock } from '@/api/serverClock'
import { readChatVisualization } from './chatVisualizationRead'
import { visualizationSnapshot } from './visualizationModel'

jest.mock('@/api/insights', () => ({ readInsight: jest.fn() }))

test.each(['cached', 'compute', 'missing'])('resolves numeric insights with server-adjusted time: %s', async (mode) => {
    const device = Date.parse('2026-11-16T12:00:00Z')
    jest.useFakeTimers({ now: device })
    recordServerDate('Sun, 15 Nov 2026 12:00:00 GMT', device)
    const insight: InsightApi = {
        id: 9,
        short_id: mode === 'missing' ? 'other' : '1234',
        name: 'Visits',
        derived_name: null,
        query: {
            kind: 'InsightVizNode',
            source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'visit' }] },
        },
        result: [{ data: [12], days: ['2026-11-15'] }],
        last_refresh: '2026-11-15T11:00:00Z',
        cache_target_age: mode === 'cached' ? '2026-11-15T13:00:00Z' : null,
        next_allowed_client_refresh: null,
    }
    jest.mocked(readInsight).mockImplementation(async (target, { refresh }) =>
        refresh === 'blocking' && target.id !== 9 ? { ...insight, result: null } : insight
    )
    try {
        const cached: unknown[] = []
        const result = await readChatVisualization({
            query: { kind: 'PathsQuery' },
            shortId: '1234',
            scope: null,
            signal: new AbortController().signal,
            onCached: (snapshot) => cached.push(snapshot),
        })
        if (mode === 'missing') {
            expect(result).toBeNull()
            expect(cached).toEqual([])
        } else {
            expect(result).toMatchObject({ insightId: 9, readAt: device, inProgressFrom: '2026-11-15' })
            expect(cached).toEqual([expect.objectContaining({ inProgressFrom: '2026-11-15' })])
            expect(visualizationSnapshot(insight.query, insight.result)).toMatchObject({
                readAt: device,
                lastRefreshAt: '2026-11-15T12:00:00.000Z',
                inProgressFrom: '2026-11-15',
            })
        }
    } finally {
        resetServerClock()
        jest.useRealTimers()
        jest.resetAllMocks()
    }
})
