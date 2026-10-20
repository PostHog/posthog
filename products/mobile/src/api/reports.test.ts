import { setAuthProvider } from './client'
import { dismissReport, fetchInboxPage, fetchLatestReviewerArtefact, INBOX_PAGE_SIZE, resolveReport } from './reports'

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
        await fetchInboxPage(offset)

        const url = new URL(urls[0] ?? '')
        expect(url.pathname).toBe('/api/projects/2/signals/reports/')
        expect(Object.fromEntries(url.searchParams)).toEqual({
            view: 'for_you',
            sort: 'priority',
            limit: String(INBOX_PAGE_SIZE),
            offset: String(offset),
        })
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

        await expect(fetchLatestReviewerArtefact('report-1')).resolves.toMatchObject(assignment)
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

        await expect(fetchLatestReviewerArtefact('report-1')).rejects.toThrow('Invalid report artefact page')
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    })

    test.each([
        {
            name: 'resolve sends the reason and the trimmed note',
            send: () => resolveReport('report-1', 'pr_merged', '  Fixed in #12 \n'),
            body: { state: 'resolved', dismissal_reason: 'pr_merged', dismissal_note: 'Fixed in #12' },
        },
        {
            name: 'dismiss leaves out a blank note',
            send: () => dismissReport('report-1', 'other', '   '),
            body: { state: 'suppressed', dismissal_reason: 'other' },
        },
        {
            name: 'a long note is cut to the API limit',
            send: () => dismissReport('report-1', 'analysis_wrong', 'x'.repeat(4100)),
            body: { state: 'suppressed', dismissal_reason: 'analysis_wrong', dismissal_note: 'x'.repeat(4000) },
        },
    ])('$name', async ({ send, body }) => {
        await send()

        expect(new URL(urls[0] ?? '').pathname).toBe('/api/projects/2/signals/reports/report-1/state/')
        expect(bodies[0]).toEqual(body)
    })
})
