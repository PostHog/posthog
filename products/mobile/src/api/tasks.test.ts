import { setAuthProvider } from './client'
import { listMySessions, SESSION_LIST_LIMIT } from './tasks'

describe('listMySessions', () => {
    afterEach(() => {
        setAuthProvider(null)
    })

    test('asks for the user chats and leaves out scout runs', async () => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        const fetchMock = jest.fn(async (_url: string) => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () => JSON.stringify({ results: [] }),
        }))
        globalThis.fetch = fetchMock as unknown as typeof fetch

        await listMySessions(7)

        const url = new URL(fetchMock.mock.calls[0]?.[0] ?? '')
        expect(url.pathname).toBe('/api/projects/2/tasks/')
        expect(Object.fromEntries(url.searchParams)).toEqual({
            created_by: '7',
            ordering: '-last_activity_at',
            basic: 'true',
            limit: String(SESSION_LIST_LIMIT),
            exclude_origin_product: 'signals_scout',
        })
    })
})
