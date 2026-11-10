import { reportFixture } from '@/model/adapters/testFixtures'

import { setAuthProvider } from './client'
import { dismissReport, fetchInboxPage, fetchLatestReviewerArtefact, INBOX_PAGE_SIZE, resolveReport } from './reports'

const SCOPE = { host: 'https://app.example.com', projectId: 2 }

describe('reports api', () => {
    const urls: string[] = []
    const bodies: unknown[] = []

    beforeEach(() => {
        urls.length = 0
        bodies.length = 0
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
            urls.push(url)
            bodies.push(typeof init?.body === 'string' ? JSON.parse(init.body) : undefined)
            return {
                ok: true,
                status: 200,
                headers: { get: () => null },
                text: async () => JSON.stringify({ count: 0, next: null, results: [] }),
            } as unknown as Response
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test.each([0, INBOX_PAGE_SIZE])('the inbox asks for personal reports at offset %i', async (offset) => {
        await expect(fetchInboxPage(SCOPE, offset)).resolves.toEqual({ count: 0, next: null, results: [] })

        const url = new URL(urls[0] ?? '')
        expect(url.pathname).toBe('/api/projects/2/signals/reports/')
        expect(Object.fromEntries(url.searchParams)).toEqual({
            view: 'for_you',
            sort: 'priority',
            limit: String(INBOX_PAGE_SIZE),
            offset: String(offset),
        })
    })

    test.each([
        undefined,
        [],
        { count: 1 },
        { results: [null] },
        { results: [{}] },
        { count: 1, next: null, results: [{ id: 'synthetic-report' }] },
        ...[
            { id: '' },
            { title: {} },
            { status: null },
            { source_products: null },
            { source_products: [42] },
            { created_at: 'invalid' },
            { updated_at: null },
            { signal_count: -1 },
            { is_suggested_reviewer: 'yes' },
            { implementation_pr_url: {} },
            { pull_requests: null },
            { pull_requests: [null] },
            { pull_requests: [{ url: 42 }] },
            { assignee: [] },
            { assignee: { kind: {} } },
            { ranking: { scores: { pr_merged: 'high' } } },
        ].map((fields) => ({ count: 1, next: null, results: [{ ...reportFixture(), ...fields }] })),
        { count: '1', results: [reportFixture()] },
        { count: 1, next: {}, results: [reportFixture()] },
    ])('rejects an invalid inbox page: %p', async (body) => {
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () => JSON.stringify(body) ?? '',
        })) as unknown as typeof fetch

        await expect(fetchInboxPage(SCOPE, 0)).rejects.toThrow("Couldn't load your inbox. Try again.")
    })

    test.each([
        null,
        { status: 'not_available', model: null, scored_at: null, predictions: [] },
        { status: 'unscored', model: null, scored_at: null, predictions: [] },
        {
            status: 'scored',
            model: 'example-model',
            scored_at: '2026-10-01T00:00:00Z',
            predictions: [{ outcome: 'pr_merged', probability: 0.5, lift: null, readable: true }],
        },
        { scores: { pr_merged: 0.5 } },
    ])('accepts current and legacy rankings with nullable titles and unknown sources: %p', async (ranking) => {
        const report = {
            ...reportFixture({ title: null, source_products: ['future_source'], assignee: null }),
            ranking,
        }
        const page = { count: 1, next: null, results: [report] }
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () => JSON.stringify(page),
        })) as unknown as typeof fetch
        await expect(fetchInboxPage(SCOPE, 0)).resolves.toEqual(page)
    })

    test('finds the newest reviewer assignment beyond the first artefact page', async () => {
        const assignment = { id: 'assignment', type: 'suggested_reviewers', content: [{ github_login: 'reviewer' }] }
        const pages = [
            {
                count: 101,
                next: 'https://app.example.com/api/projects/2/signals/reports/report-1/artefacts/?limit=100&offset=100',
                results: Array.from({ length: 100 }, (_, index) => ({ id: `newer-${index}`, type: 'note' })),
            },
            { count: 101, next: null, results: [assignment] },
        ]
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () => JSON.stringify(pages.shift()),
        })) as unknown as typeof fetch

        await expect(fetchLatestReviewerArtefact(SCOPE, 'report-1')).resolves.toMatchObject(assignment)
        const requests = jest.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url)))
        expect(requests.map((url) => url.searchParams.get('offset'))).toEqual([null, '100'])
    })

    test('rejects an artefact page from another origin', async () => {
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () =>
                JSON.stringify({ count: 101, next: 'https://other.example.com/steal?offset=100', results: [] }),
        })) as unknown as typeof fetch

        await expect(fetchLatestReviewerArtefact(SCOPE, 'report-1')).rejects.toThrow('Invalid report artefact page')
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    })

    test.each([
        {
            name: 'resolve sends the reason and the trimmed note',
            send: () => resolveReport(SCOPE, 'report-1', 'pr_merged', '  Fixed in #12 \n'),
            body: { state: 'resolved', dismissal_reason: 'pr_merged', dismissal_note: 'Fixed in #12' },
        },
        {
            name: 'dismiss leaves out a blank note',
            send: () => dismissReport(SCOPE, 'report-1', 'other', '   '),
            body: { state: 'suppressed', dismissal_reason: 'other' },
        },
        {
            name: 'a long note is cut to the API limit',
            send: () => dismissReport(SCOPE, 'report-1', 'analysis_wrong', 'x'.repeat(4100)),
            body: { state: 'suppressed', dismissal_reason: 'analysis_wrong', dismissal_note: 'x'.repeat(4000) },
        },
    ])('$name', async ({ send, body }) => {
        await send()

        expect(new URL(urls[0] ?? '').pathname).toBe('/api/projects/2/signals/reports/report-1/state/')
        expect(bodies[0]).toEqual(body)
    })
})
