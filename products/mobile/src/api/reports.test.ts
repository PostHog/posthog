import { setAuthProvider } from './client'
import { dismissReport, fetchInboxPage, INBOX_PAGE_SIZE, resolveReport } from './reports'

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

    test('the inbox asks for the next page of only the reports for the user', async () => {
        await fetchInboxPage(INBOX_PAGE_SIZE)

        const url = new URL(urls[0] ?? '')
        expect(url.pathname).toBe('/api/projects/2/signals/reports/for_you/')
        expect(Object.fromEntries(url.searchParams)).toEqual({
            include_unowned: 'false',
            limit: String(INBOX_PAGE_SIZE),
            offset: String(INBOX_PAGE_SIZE),
        })
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
