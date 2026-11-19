import { QueryClient } from '@tanstack/react-query'

import { type InsightApi, readInsight } from '@/api/insights'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import { type ItemContext, insightItem, insightQueryKey } from './items'
import { pinRangeLabel } from './snapshotChart'
import { useItemErrors } from './viewsCache'

jest.mock('@/api/insights', () => ({
    ...jest.requireActual('@/api/insights'),
    readInsight: jest.fn(),
}))

const TARGET = { shortId: 'example', id: 7, dashboardRef: null, override: null }

function response(overrides: Partial<InsightApi>): InsightApi {
    return {
        id: 7,
        short_id: 'example',
        name: 'Example insight',
        derived_name: null,
        query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
        result: [],
        last_refresh: '2026-10-16T12:00:00Z',
        cache_target_age: '2026-10-16T17:00:00Z',
        next_allowed_client_refresh: '2026-10-16T12:05:00Z',
        is_cached: true,
        ...overrides,
    }
}

describe('Views insight reads', () => {
    let context: ItemContext

    beforeEach(() => {
        context = {
            client: new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } }),
            scope: null,
            demo: false,
        }
        useItemErrors.getState().reset()
        jest.mocked(readInsight).mockReset()
    })

    afterEach(() => context.client.clear())

    test.each([
        [undefined, true, 'Oct 1 – 20'],
        [false, false, 'Last 7 days'],
    ])(
        'keeps a dashboard tile range across a direct pin refresh, with explicit override %s',
        async (own, expected, label) => {
            const target = { ...TARGET, dashboardRef: '12', usesOwnRange: own }
            const data = response({
                query: {
                    kind: 'InsightVizNode',
                    source: { kind: 'TrendsQuery', series: [], dateRange: { date_from: '-7d' } },
                },
                resolved_date_range: { date_from: '2026-10-01T00:00:00Z', date_to: '2026-10-20T23:59:59Z' },
            })
            context.client.setQueryData(
                insightQueryKey(null, target),
                insightSnapshot(data, undefined, { readAt: 1, serverNow: 1, usesOwnRange: true })
            )
            jest.mocked(readInsight).mockResolvedValue(data)

            const item = insightItem(context, target)
            await item.read('blocking', new AbortController().signal)

            const snapshot = context.client.getQueryData<ReturnType<typeof insightSnapshot>>(
                insightQueryKey(null, target)
            )
            expect(snapshot).toMatchObject({ usesOwnRange: expected })
            expect(snapshot && pinRangeLabel(snapshot)).toBe(label)
        }
    )

    test('an HTTP 200 query error keeps metadata and exposes a recoverable error until a good result arrives', async () => {
        jest.mocked(readInsight)
            .mockResolvedValueOnce(response({ result: null, query_status: { error: true } }))
            .mockResolvedValueOnce(response({ result: [{ days: ['2026-10-15'], data: [3] }] }))
        const item = insightItem(context, TARGET)

        await expect(item.read('blocking', new AbortController().signal)).resolves.toMatchObject({ status: 'failed' })
        expect(item.snapshot()).toMatchObject({ name: 'Example insight', lastRefreshAt: null, refreshFailed: true })
        expect(useItemErrors.getState().errors[item.key]).toBe('failed')

        await expect(item.read('blocking', new AbortController().signal)).resolves.toMatchObject({ status: 'ok' })
        expect(item.snapshot()).toMatchObject({ lastRefreshAt: '2026-10-16T12:00:00Z', refreshFailed: false })
        expect(useItemErrors.getState().errors[item.key]).toBeUndefined()
    })

    test('a response arriving after its read was aborted cannot replace the cache', async () => {
        let resolve: (value: InsightApi) => void = () => undefined
        jest.mocked(readInsight).mockImplementationOnce(
            () =>
                new Promise<InsightApi>((done) => {
                    resolve = done
                })
        )
        const item = insightItem(context, TARGET)
        const controller = new AbortController()
        const read = item.read('blocking', controller.signal)

        controller.abort()
        resolve(response({}))

        await expect(read).rejects.toMatchObject({ name: 'AbortError' })
        expect(item.snapshot()).toBeUndefined()
    })
})
