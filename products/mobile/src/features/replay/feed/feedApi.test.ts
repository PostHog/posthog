import { setAuthProvider } from '@/api/client'

import { fetchFeedRecordings } from './feedApi'

function jsonResponse(body: unknown): Response {
    return { ok: true, status: 200, headers: { get: () => null }, text: async () => JSON.stringify(body) } as never
}

function requestedUrls(): URL[] {
    return (fetch as jest.Mock).mock.calls.map(([url]) => new URL(url as string))
}

describe('feed recordings queries', () => {
    beforeEach(() =>
        setAuthProvider({
            getAuth: () => ({ host: 'https://example.com', accessToken: 'token', projectId: 7, session: 1 }),
            refreshAccessToken: async () => null,
        })
    )
    afterEach(() => setAuthProvider(null))

    test.each(['newest', 'rage', 'errors'] as const)(
        '%s stops an hour back, before recordings in progress',
        async (source) => {
            globalThis.fetch = jest.fn().mockResolvedValue(jsonResponse({ results: [], has_next: false }))
            await fetchFeedRecordings(source, undefined)
            const [url] = requestedUrls()
            expect(url?.pathname).toBe('/api/projects/7/session_recordings/')
            expect(url?.searchParams.get('date_to')).toBe('-1h')
            expect(url?.searchParams.get('date_from')).toBe('-7d')
        }
    )

    test('highlights read the Replay Vision feed, then its recordings by id in the feed order', async () => {
        globalThis.fetch = jest
            .fn()
            .mockResolvedValueOnce(
                jsonResponse({
                    results: [{ observation: { session_id: 'b' } }, { observation: { session_id: 'a' } }],
                    has_more: true,
                    as_of: '2026-11-18T10:00:00Z',
                })
            )
            .mockResolvedValueOnce(jsonResponse({ results: [{ id: 'a' }, { id: 'b' }] }))
        const page = await fetchFeedRecordings('highlights', undefined, undefined, true)
        const [feed, list] = requestedUrls()
        expect(feed?.pathname).toBe('/api/projects/7/vision/scanners/highlight_feed/')
        expect(JSON.parse(list?.searchParams.get('session_ids') ?? '[]')).toEqual(['b', 'a'])
        expect(list?.searchParams.get('filter_test_accounts')).toBe('true')
        expect(page.results?.map((row) => row.id)).toEqual(['b', 'a'])
        expect(page.next_cursor).toBe('10|2026-11-18T10:00:00Z')
    })
})
