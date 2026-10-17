import { QueryClient } from '@tanstack/react-query'

import { type InsightApi, readInsight } from '@/api/insights'

import { type ItemContext, insightItem } from './items'
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
        context = { client: new QueryClient(), scope: null, demo: false }
        useItemErrors.getState().reset()
        jest.mocked(readInsight).mockReset()
    })

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
