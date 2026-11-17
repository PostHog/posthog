import { setAuthProvider } from './client'
import { sessionEventsQuery } from './recordings'
import { fetchFrameUrl, requestSessionSummary } from './replayVision'

describe('replay API', () => {
    beforeEach(() =>
        setAuthProvider({
            getAuth: () => ({ host: 'https://example.com', accessToken: 'token', projectId: 7, session: 1 }),
            refreshAccessToken: async () => null,
        })
    )
    afterEach(() => setAuthProvider(null))

    test('a frame resolves to the signed URL without following the redirect', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 302,
            headers: { get: (name: string) => (name === 'Location' ? 'https://storage.example.com/frame.png' : null) },
        })
        await expect(fetchFrameUrl('obs-1', 2)).resolves.toBe('https://storage.example.com/frame.png')
        expect(fetch).toHaveBeenCalledWith(
            'https://example.com/api/projects/7/vision/observations/obs-1/thumbnail/?chapter=2',
            expect.objectContaining({ redirect: 'manual' })
        )
    })

    test('summarize runs the built-in summary and reads its outcome for the session', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            status: 202,
            text: async () =>
                JSON.stringify({
                    scan_id: 'scan-1',
                    started: 0,
                    results: [{ session_id: 's-1', scan_outcome: 'skipped_quota' }],
                }),
        })
        await expect(requestSessionSummary('s-1')).resolves.toBe('skipped_quota')
        const init = (fetch as jest.Mock).mock.calls[0][1] as RequestInit
        expect(JSON.parse(init.body as string)).toEqual({ built_in: 'summarize_recording', session_ids: ['s-1'] })
    })

    test('the events query takes the session id as a value, never as query text', () => {
        const id = "abc' OR 1=1 --"
        const query = sessionEventsQuery(id, '2026-10-21T20:14:00Z', '2026-10-21T20:18:12Z', 'problems')
        expect(query.query).not.toContain(id)
        expect(query.values).toEqual({
            session_id: id,
            date_from: '2026-10-21T20:13:00.000Z',
            date_to: '2026-10-21T20:19:12.000Z',
        })
    })
})
