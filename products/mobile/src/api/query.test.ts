import { setAuthProvider } from './client'
import { queryKeys, type RunQueryOptions, runQuery } from './query'

const TRENDS = { results: [{ data: [1, 2], days: ['2026-10-12', '2026-10-13'] }] }
const SCOPE = { host: 'https://app.example.com', projectId: 2 }

describe('query api', () => {
    const calls: { url: string; method: string; body: unknown }[] = []
    let replies: unknown[] = []

    beforeEach(() => {
        calls.length = 0
        replies = []
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string, init: RequestInit) => {
            calls.push({ url, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : null })
            return {
                ok: true,
                status: 200,
                headers: { get: () => null },
                text: async () => JSON.stringify(replies.shift()),
            } as unknown as Response
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('posts the query and returns an inline response without polling', async () => {
        replies = [TRENDS]

        await expect(runQuery({ kind: 'TrendsQuery' })).resolves.toEqual(TRENDS)
        expect(calls).toHaveLength(1)
        expect(calls[0]).toMatchObject({
            url: 'https://app.example.com/api/projects/2/query/',
            method: 'POST',
            body: { query: { kind: 'TrendsQuery' }, refresh: 'blocking' },
        })
    })

    test('polls a running query until it completes and returns its results', async () => {
        replies = [
            { query_status: { id: 'q 1', complete: false } },
            { query_status: { id: 'q 1', complete: false } },
            { query_status: { id: 'q 1', complete: true, results: TRENDS } },
        ]

        await expect(runQuery({ kind: 'TrendsQuery' }, { pollIntervalMs: 0 })).resolves.toEqual(TRENDS)
        expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
            'POST https://app.example.com/api/projects/2/query/',
            'GET https://app.example.com/api/projects/2/query/q%201/',
            'GET https://app.example.com/api/projects/2/query/q%201/',
        ])
    })

    test('returns a running status as it is when polling is off', async () => {
        const running = { query_status: { id: 'q', complete: false } }
        replies = [running]

        await expect(runQuery({ kind: 'TrendsQuery' }, { refresh: 'force_blocking', poll: false })).resolves.toEqual(
            running
        )
        expect(calls).toHaveLength(1)
        expect(calls[0]?.body).toMatchObject({ refresh: 'force_blocking' })
    })

    test.each<[string, unknown[], RunQueryOptions, string]>([
        [
            'a failed status',
            [{ query_status: { id: 'q', complete: true, error: true, error_message: 'Bad' } }],
            {},
            'Bad',
        ],
        ['a query past the deadline', [{ query_status: { id: 'q', complete: false } }], { timeoutMs: 0 }, 'too long'],
    ])('rejects %s', async (_name, queued, options, message) => {
        replies = queued
        await expect(runQuery({ kind: 'TrendsQuery' }, options)).rejects.toThrow(message)
    })

    test('stops polling when the caller aborts', async () => {
        replies = [{ query_status: { id: 'q', complete: false } }]
        const controller = new AbortController()
        const running = runQuery({ kind: 'TrendsQuery' }, { signal: controller.signal, pollIntervalMs: 60_000 })
        await Promise.resolve()
        controller.abort()

        await expect(running).rejects.toMatchObject({ name: 'AbortError' })
        expect(calls).toHaveLength(1)
    })

    test('equal queries share a cache key whatever their key order', () => {
        expect(queryKeys.run(SCOPE, { kind: 'TrendsQuery', interval: 'day', series: [{ a: 1, b: 2 }] })).toEqual(
            queryKeys.run(SCOPE, { series: [{ b: 2, a: 1 }], interval: 'day', kind: 'TrendsQuery' })
        )
        expect(queryKeys.run(SCOPE, { interval: 'day' })).not.toEqual(queryKeys.run(SCOPE, { interval: 'week' }))
    })
})
