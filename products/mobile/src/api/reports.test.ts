import { setAuthProvider } from './client'
import { fetchInboxPage, INBOX_PAGE_SIZE } from './reports'

describe('reports api', () => {
    const urls: string[] = []

    beforeEach(() => {
        urls.length = 0
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string) => {
            urls.push(url)
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
})
