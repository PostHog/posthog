import { setAuthProvider } from './client'
import { getInsightSummary } from './insights'

describe('insight summary', () => {
    beforeEach(() =>
        setAuthProvider({
            getAuth: () => ({ host: 'https://example.com', accessToken: 'token', projectId: 7, session: 1 }),
            refreshAccessToken: async () => null,
        })
    )
    afterEach(() => setAuthProvider(null))
    test('only reads the cached insight and falls back to derived name', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            text: async () => JSON.stringify({ name: '', derived_name: 'Count', description: '' }),
        })
        await expect(getInsightSummary('a/b')).resolves.toEqual({ name: 'Count', description: null })
        expect(fetch).toHaveBeenCalledWith(
            'https://example.com/api/projects/7/insights/a%2Fb/?refresh=force_cache',
            expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) })
        )
    })
    test.each([404, 403, 500])('handles status %s', async (status) => {
        globalThis.fetch = jest
            .fn()
            .mockResolvedValue({ ok: false, status, headers: { get: () => null }, text: async () => '{}' })
        if (status === 404) await expect(getInsightSummary('a')).resolves.toBeNull()
        else await expect(getInsightSummary('a')).rejects.toMatchObject({ status })
    })
})
