import { setAuthProvider } from './client'
import { fetchInsightMetadata, getInsightSummary, readInsight } from './insights'

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
    test('reads only metadata for an all-digit short id without resolving it as a primary key', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            text: async () => JSON.stringify({ results: [{ id: 9, short_id: '1234', name: 'Signups' }] }),
        })
        await expect(fetchInsightMetadata('1234')).resolves.toMatchObject({ id: 9, short_id: '1234' })
        expect(fetch).toHaveBeenCalledWith(
            'https://example.com/api/projects/7/insights/?basic=true&short_id=1234&refresh=force_cache',
            expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) })
        )
    })
    test('keeps the conversation project for a saved insight and its numeric short-id fallback', async () => {
        const fetch = jest
            .fn()
            .mockResolvedValueOnce({ ok: true, text: async () => JSON.stringify({ id: 1234, short_id: 'different' }) })
            .mockResolvedValueOnce({
                ok: true,
                text: async () => JSON.stringify({ results: [{ id: 9, short_id: '1234', name: 'Signups' }] }),
            })
        globalThis.fetch = fetch
        await expect(
            readInsight(
                { shortId: '1234' },
                { refresh: 'blocking', scope: { host: 'https://example.com', projectId: 42 } }
            )
        ).resolves.toMatchObject({ id: 9, short_id: '1234' })
        expect(fetch.mock.calls.map(([url]) => url)).toEqual([
            'https://example.com/api/projects/42/insights/1234/?refresh=blocking',
            'https://example.com/api/projects/42/insights/?short_id=1234&refresh=force_cache',
        ])
    })
    test.each([404, 403, 500])('handles status %s', async (status) => {
        globalThis.fetch = jest
            .fn()
            .mockResolvedValue({ ok: false, status, headers: { get: () => null }, text: async () => '{}' })
        if (status === 404) await expect(getInsightSummary('a')).resolves.toBeNull()
        else await expect(getInsightSummary('a')).rejects.toMatchObject({ status })
    })
})
