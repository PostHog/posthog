import { setAuthProvider } from './client'
import { fetchInboxReports } from './reports'

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

    test('the fallback inbox keeps reports that already have a PR', async () => {
        await fetchInboxReports()

        const url = new URL(urls[0] ?? '')
        expect(url.pathname).toBe('/api/projects/2/signals/reports/')
        expect(Object.fromEntries(url.searchParams)).toEqual({
            scope: 'for_me',
            status: 'ready,pending_input,failed',
            sort: 'priority',
            limit: '50',
        })
    })
})
