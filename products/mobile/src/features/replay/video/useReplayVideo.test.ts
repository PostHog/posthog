import { act, renderHook, waitFor } from '@testing-library/react-native'

import { setAuthProvider } from '@/api/client'

import { REPLAY_VIDEO_POLL_MS, useReplayVideo } from './useReplayVideo'

const EXPORTS_PATH = '/api/projects/7/exports/'
const SIGNED_URL = 'https://storage.example.com/replay.mp4?sig=1'

function json(body: unknown, status = 200): Response {
    return {
        ok: status >= 200 && status < 300,
        status,
        url: '',
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

function redirectToStorage(): Response {
    return {
        ok: false,
        status: 302,
        url: '',
        headers: { get: (name: string) => (name === 'Location' ? SIGNED_URL : null) },
    } as unknown as Response
}

function exportBody(id: number, fields: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        id,
        export_format: 'video/mp4',
        created_at: new Date(Date.now() - 60_000).toISOString(),
        has_content: false,
        export_context: { session_recording_id: 's-1', timestamp: 0, duration: 120 },
        filename: 'replay-s-1',
        expires_after: null,
        exception: null,
        ...fields,
    }
}

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>

function mockApi(handler: Handler): jest.Mock {
    const mock = jest.fn(async (url: string, init: RequestInit) => handler(new URL(url), init))
    globalThis.fetch = mock as unknown as typeof fetch
    return mock
}

async function flush(ms = 0): Promise<void> {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

describe('useReplayVideo', () => {
    beforeEach(() =>
        setAuthProvider({
            getAuth: () => ({ host: 'https://us.example.com', accessToken: 'token', projectId: 7, session: 1 }),
            refreshAccessToken: async () => null,
        })
    )
    afterEach(() => {
        jest.useRealTimers()
        setAuthProvider(null)
    })

    test('plays a finished export of the session without rendering it again', async () => {
        const api = mockApi((url) =>
            url.pathname.endsWith('/content/')
                ? redirectToStorage()
                : json({
                      results: [
                          exportBody(3, {
                              has_content: true,
                              export_context: {
                                  session_recording_id: 's-1',
                                  timestamp: 0,
                                  duration: 120,
                                  video_duration_s: 40,
                              },
                          }),
                      ],
                  })
        )
        const hook = renderHook(() => useReplayVideo({ sessionId: 's-1', durationSeconds: 120 }))
        act(() => hook.result.current.start())
        await waitFor(() => expect(hook.result.current.state.status).toBe('ready'))
        expect(hook.result.current.state).toMatchObject({
            exportId: 3,
            reused: true,
            source: { uri: SIGNED_URL },
            context: { video_duration_s: 40 },
        })
        expect(api.mock.calls.some(([, init]) => init.method === 'POST')).toBe(false)
    })

    test('renders the recording, polls every few seconds through a rate limit, then plays it', async () => {
        jest.useFakeTimers()
        let polls = 0
        const api = mockApi((url, init) => {
            if (url.pathname.endsWith('/content/')) {
                return redirectToStorage()
            }
            if (url.pathname === EXPORTS_PATH) {
                return init.method === 'POST' ? json(exportBody(9), 201) : json({ results: [] })
            }
            polls += 1
            return polls === 1 ? json({}, 429) : json(exportBody(9, { has_content: polls === 3 }))
        })
        const hook = renderHook(() => useReplayVideo({ sessionId: 's-1', durationSeconds: 125.7 }))
        act(() => hook.result.current.start())
        await flush()
        expect(hook.result.current.state).toMatchObject({ status: 'preparing', exportId: 9, reused: false })
        const post = api.mock.calls.find(([, init]) => init.method === 'POST')?.[1] as RequestInit
        expect(JSON.parse(post.body as string)).toMatchObject({
            export_format: 'video/mp4',
            export_context: { session_recording_id: 's-1', timestamp: 0, duration: 125 },
        })

        await flush(REPLAY_VIDEO_POLL_MS - 1)
        expect(polls).toBe(0)
        await flush(1)
        await flush(REPLAY_VIDEO_POLL_MS)
        expect(polls).toBe(2)
        expect(hook.result.current.state.status).toBe('preparing')
        await flush(REPLAY_VIDEO_POLL_MS)
        expect(polls).toBe(3)
        expect(hook.result.current.state).toMatchObject({
            status: 'ready',
            exportId: 9,
            reused: false,
            source: { uri: SIGNED_URL },
        })
    })

    test('shows the server reason when the team reached its monthly video cap', async () => {
        const reason = 'Your team has reached the limit of 10 full video exports this month.'
        mockApi((_url, init) =>
            init.method === 'POST' ? json({ export_limit_exceeded: [reason] }, 400) : json({ results: [] })
        )
        const hook = renderHook(() => useReplayVideo({ sessionId: 's-1', durationSeconds: 120 }))
        act(() => hook.result.current.start())
        await waitFor(() => expect(hook.result.current.state.status).toBe('error'))
        expect(hook.result.current.state).toEqual({ status: 'error', kind: 'limit_reached', message: reason })
    })

    test('unmounting cancels the request in flight and stops polling', async () => {
        jest.useFakeTimers()
        const pollSignals: AbortSignal[] = []
        const api = mockApi((url, init) => {
            if (url.pathname === EXPORTS_PATH) {
                return json({ results: [exportBody(5)] })
            }
            pollSignals.push(init.signal as AbortSignal)
            return new Promise<Response>(() => undefined)
        })
        const hook = renderHook(() => useReplayVideo({ sessionId: 's-1', durationSeconds: 120 }))
        act(() => hook.result.current.start())
        await flush()
        expect(hook.result.current.state).toMatchObject({ status: 'preparing', exportId: 5, reused: true })
        await flush(REPLAY_VIDEO_POLL_MS)
        expect(pollSignals).toHaveLength(1)

        hook.unmount()
        expect(pollSignals[0]?.aborted).toBe(true)
        const calls = api.mock.calls.length
        await flush(REPLAY_VIDEO_POLL_MS * 3)
        expect(api.mock.calls.length).toBe(calls)
    })
})
