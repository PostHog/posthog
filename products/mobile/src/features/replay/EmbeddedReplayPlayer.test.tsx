import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'

import { setAuthProvider } from '@/api/client'
import { setSessionTokens } from '@/auth/tokens'

import { EmbeddedReplayPlayer } from './EmbeddedReplayPlayer'

jest.mock('./player/player.bundle.json', () => 'window.testRenderer = true;')

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
    return {
        ok: true,
        status: 200,
        headers: new Headers(),
        text: async () => (raw ? value : JSON.stringify(value)),
    } as Response
}

beforeEach(() => {
    jest.clearAllMocks()
    setAuthProvider({
        getAuth: () => ({ ...mockScope, accessToken: 'invented-native-only-token', session: 1 }),
        refreshAccessToken: async () => null,
    })
})
afterEach(() => setAuthProvider(null))

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
        await act(async () => resolveBlock(response('{"type":2}', true)))
        expect(mockInject).not.toHaveBeenCalled()
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
    await act(async () => resolveBlock(response('private recording data', true)))
    expect(mockInject).not.toHaveBeenCalled()
    unmount()
})
