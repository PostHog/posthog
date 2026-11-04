import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import { resetBudgets, trySpend } from '@/api/budget'
import { setAuthProvider } from '@/api/client'
import { setSessionTokens } from '@/auth/tokens'

import { EmbeddedReplayPlayer } from './EmbeddedReplayPlayer'

jest.mock('./player/player.bundle.json', () => 'window.testRenderer = true;')
jest.mock('expo/fetch', () => ({
    fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args),
}))

const mockInject = jest.fn()
const mockScope = { host: 'https://app.example.com', projectId: 2 }
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default)
jest.mock('expo-crypto', () => ({ randomUUID: () => 'test-nonce' }))
jest.mock('react-native-webview', () => {
    const React = require('react')
    const { View } = require('react-native')
    return {
        __esModule: true,
        default: React.forwardRef((props: object, ref: unknown) => {
            React.useImperativeHandle(ref, () => ({ injectJavaScript: mockInject }))
            return <View {...props} />
        }),
    }
})

function response(value: unknown, raw = false): Response {
    let read = false
    return {
        ok: true,
        status: 200,
        headers: new Headers(),
        text: async () => (raw ? value : JSON.stringify(value)),
        body: raw
            ? {
                  getReader: () => ({
                      read: async () => {
                          if (read) return { done: true, value: undefined }
                          read = true
                          return { done: false, value: new TextEncoder().encode(String(value)) }
                      },
                      cancel: async () => undefined,
                      releaseLock: () => undefined,
                  }),
              }
            : null,
    } as Response
}

beforeEach(() => {
    jest.clearAllMocks()
    resetBudgets()
    setAuthProvider({
        getAuth: () => ({ ...mockScope, accessToken: 'invented-native-only-token', session: 1 }),
        refreshAccessToken: async () => null,
    })
})
afterEach(() => {
    setAuthProvider(null)
    jest.useRealTimers()
})

test.each(['https://mobile-replay.invalid', 'https://mobile-replay.invalid/'])(
    'loads the recording through native auth for %s and cancels on close',
    async (playerUrl) => {
        let blockSignal: AbortSignal | null | undefined
        let resolveBlock: (response: Response) => void = () => undefined
        globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
            if (String(_url).includes('start_blob_key')) {
                blockSignal = init.signal
                expect(init.headers).toMatchObject({ Authorization: 'Bearer invented-native-only-token' })
                return new Promise<Response>((resolve) => {
                    resolveBlock = resolve
                })
            }
            return Promise.resolve(response({ sources: [{ source: 'blob_v2', blob_key: '7' }] }))
        }) as typeof fetch
        const { unmount, rerender } = render(
            <EmbeddedReplayPlayer sessionId="example-session" seconds={12} startedAt={null} onClose={() => undefined} />
        )
        const view = await screen.findByTestId('replay-player-webview')
        expect(JSON.stringify(view.props.source)).not.toContain('invented-native-only-token')
        const initialHtml = view.props.source.html
        rerender(
            <EmbeddedReplayPlayer sessionId="example-session" seconds={40} startedAt={null} onClose={() => undefined} />
        )
        expect(screen.getByTestId('replay-player-webview').props.source.html).toBe(initialHtml)
        expect(view.props.incognito).toBe(true)
        expect(view.props.source).not.toHaveProperty('headers')
        const message = (data: unknown): void =>
            fireEvent(view, 'message', {
                nativeEvent: { url: playerUrl, data: JSON.stringify(data) },
            })
        fireEvent(view, 'message', {
            nativeEvent: { url: 'https://example.com/', data: '{"type":"block","id":1,"index":0}' },
        })
        expect(fetch).toHaveBeenCalledTimes(1)
        message({ type: 'block', id: 1, index: 99 })
        expect(fetch).toHaveBeenCalledTimes(1)
        message({ type: 'block', id: 2, index: 0 })
        expect(fetch).toHaveBeenCalledTimes(2)
        expect(jest.mocked(fetch).mock.calls[1]?.[0]).toContain('start_blob_key=7')
        unmount()
        expect(blockSignal?.aborted).toBe(true)
        const injectionsAfterClose = mockInject.mock.calls.length
        await act(async () => resolveBlock(response('{"type":2}', true)))
        expect(mockInject).toHaveBeenCalledTimes(injectionsAfterClose)
    }
)

test('rejects a stale block response when the app session changes', async () => {
    let resolveBlock: (response: Response) => void = () => undefined
    globalThis.fetch = jest.fn((url: string) =>
        String(url).includes('start_blob_key')
            ? new Promise<Response>((resolve) => {
                  resolveBlock = resolve
              })
            : Promise.resolve(response({ sources: [{ source: 'blob_v2', blob_key: '0' }] }))
    ) as typeof fetch
    const { unmount } = render(
        <EmbeddedReplayPlayer sessionId="example-session" seconds={0} startedAt={null} onClose={() => undefined} />
    )
    const view = await screen.findByTestId('replay-player-webview')
    fireEvent(view, 'message', { nativeEvent: { url: 'about:blank', data: '{"type":"block","id":1,"index":0}' } })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    setSessionTokens(null)
    const injectionsBeforeResponse = mockInject.mock.calls.length
    await act(async () => resolveBlock(response('private recording data', true)))
    expect(mockInject).toHaveBeenCalledTimes(injectionsBeforeResponse)
    unmount()
})

test.each(['downloads', 'budget'] as const)('allows startup past 30 seconds during progressing %s', async (stage) => {
    jest.useFakeTimers({ now: 0 })
    if (stage === 'budget') {
        for (let batch = 0; batch < 6; batch++) {
            if (batch > 0) await jest.advanceTimersByTimeAsync(60_000)
            while (trySpend('replay')) {}
        }
    }
    const blockCount = stage === 'downloads' ? 60 : 6
    globalThis.fetch = jest.fn((url: string) => {
        if (!String(url).includes('start_blob_key')) {
            return Promise.resolve(
                response({
                    sources: Array.from({ length: blockCount }, (_, index) => ({
                        source: 'blob_v2',
                        blob_key: String(index),
                    })),
                })
            )
        }
        if (stage === 'budget') return Promise.resolve(response('{"type":2}', true))
        return new Promise<Response>((resolve) => {
            setTimeout(() => resolve(response('{"type":2}', true)), 4000)
        })
    }) as typeof fetch
    const { unmount } = render(
        <EmbeddedReplayPlayer sessionId="example-session" seconds={0} startedAt={null} onClose={() => undefined} />
    )
    if (stage === 'budget') await act(async () => jest.advanceTimersByTimeAsync(12_000))
    const view = await screen.findByTestId('replay-player-webview')
    for (let start = 0; start < blockCount; start += 6) {
        for (let index = start; index < Math.min(start + 6, blockCount); index++) {
            fireEvent(view, 'message', {
                nativeEvent: {
                    url: 'about:blank',
                    data: JSON.stringify({ type: 'block', id: index + 1, index }),
                },
            })
        }
        await act(async () => jest.advanceTimersByTimeAsync(stage === 'downloads' ? 4000 : 72_000))
        expect(screen.queryByTestId('replay-player-error')).toBeNull()
    }
    expect(mockInject.mock.calls.filter(([script]) => script.startsWith('window.__receiveReplayBlock('))).toHaveLength(
        blockCount
    )
    fireEvent(view, 'message', { nativeEvent: { url: 'about:blank', data: '{"type":"ready"}' } })
    await act(async () => jest.advanceTimersByTimeAsync(30_000))
    expect(screen.queryByTestId('replay-player-error')).toBeNull()
    unmount()
})

test('fails a player that stops requesting blocks and cancels its pending browser work', async () => {
    jest.useFakeTimers()
    globalThis.fetch = jest.fn(async () =>
        response({ sources: [{ source: 'blob_v2', blob_key: '0' }] })
    ) as typeof fetch
    render(<EmbeddedReplayPlayer sessionId="example-session" seconds={0} startedAt={null} onClose={() => undefined} />)
    await screen.findByTestId('replay-player-webview')
    await act(async () => jest.advanceTimersByTimeAsync(30_000))
    expect(screen.getByTestId('replay-player-error')).toBeTruthy()
    expect(mockInject.mock.calls.some(([script]) => script.includes('__cancelReplayBlocks'))).toBe(true)
})
