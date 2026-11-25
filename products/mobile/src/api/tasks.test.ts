import { setAuthProvider } from './client'
import { getTaskModels, listMySessions, SESSION_LIST_LIMIT } from './tasks'

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

describe('getTaskModels', () => {
    afterEach(() => {
        setAuthProvider(null)
    })

    test.each([
        ['a row from an older server that sends no offered field', {}, true],
        ['an offered row', { offered: true }, true],
        ['a row the server no longer offers', { offered: false }, false],
    ])('reads %s', async (_case, sent, offered) => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        const row = {
            runtime_adapter: 'claude',
            model: 'claude-opus-5-5',
            display_name: 'Claude Opus 5.5',
            supported_efforts: [],
            ...sent,
        }
        globalThis.fetch = jest.fn(async () => ({
            ok: true,
            status: 200,
            headers: { get: () => null },
            text: async () => JSON.stringify({ models: [row] }),
        })) as unknown as typeof fetch

        const catalogue = await getTaskModels({ host: 'https://app.example.com', projectId: 2 })

        expect(catalogue).toEqual({ costBaseline: null, models: [{ ...row, offered }] })
    })
})
