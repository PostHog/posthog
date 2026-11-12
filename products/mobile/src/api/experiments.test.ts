import { resetBudgets } from './budget'
import { setAuthProvider } from './client'
import { fetchExperiments, fetchLatestResults, shipVariant, startRecalculation } from './experiments'
import type { ProjectScope } from './reports'

const SCOPE: ProjectScope = { host: 'https://app.example.com', projectId: 7 }

interface FakeResponse {
    status: number
    body: unknown
    headers?: Record<string, string>
}

function respond(handler: (url: URL) => FakeResponse): jest.Mock {
    const fetchMock = jest.fn(async (url: string) => {
        const { status, body, headers = {} } = handler(new URL(url))
        return {
            ok: status >= 200 && status < 300,
            status,
            headers: { get: (name: string) => headers[name] ?? null },
            text: async () => JSON.stringify(body),
        }
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    return fetchMock
}

function row(id: number): Record<string, unknown> {
    return { id, name: `Experiment ${id}`, feature_flag_key: `flag-${id}`, status: 'running' }
}

describe('experiments API', () => {
    beforeEach(() => {
        resetBudgets()
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('reads every running status at the same offset and merges them without repeats', async () => {
        const fetchMock = respond((url) => {
            const status = url.searchParams.get('status')
            const results = status === 'running' ? [row(1), row(2)] : status === 'paused' ? [row(2), row(3)] : []
            return { status: 200, body: { count: 0, next: status === 'running' ? 'next' : null, results } }
        })

        const page = await fetchExperiments(SCOPE, { status: 'running', search: ' cta ' }, undefined, 20)

        const urls = fetchMock.mock.calls.map(([url]) => new URL(url as string))
        // The screen's project, not the session's (2).
        expect(urls.every((url) => url.pathname === '/api/projects/7/experiments/')).toBe(true)
        const params = urls.map((url) => Object.fromEntries(url.searchParams))
        expect(params.map((query) => query.status).sort()).toEqual(['exposure_frozen', 'paused', 'running'])
        expect(params.every((query) => query.offset === '20' && query.search === 'cta')).toBe(true)
        expect(params.every((query) => query.order === '-start_date' && query.limit === '20')).toBe(true)
        expect(page.results.map((item) => item.id)).toEqual([1, 2, 3])
        expect(page).toMatchObject({ hasMore: true, nextOffset: 40 })
    })

    test('reads no stored results as null', async () => {
        respond(() => ({ status: 404, body: { detail: 'No completed recalculation found' } }))

        await expect(fetchLatestResults(SCOPE, 7)).resolves.toBeNull()
    })

    test('turns the five-minute refresh window into a wait', async () => {
        respond(() => ({ status: 429, body: { detail: 'Too soon' }, headers: { 'Retry-After': '184' } }))

        await expect(startRecalculation(SCOPE, 7)).resolves.toEqual({ run: null, retryAfterMs: 184_000 })
    })

    test('reads an approval policy hold on ship as a pending change request', async () => {
        respond(() => ({
            status: 409,
            body: { code: 'change_request_pending', change_request_id: 'cr-1', detail: 'Needs approval' },
        }))

        await expect(shipVariant(SCOPE, 7, { variant_key: 'test' })).resolves.toEqual({
            status: 'needs_approval',
            changeRequestId: 'cr-1',
            code: 'change_request_pending',
        })
    })
})
