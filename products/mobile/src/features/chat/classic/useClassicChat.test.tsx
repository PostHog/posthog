import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import { randomUUID } from 'expo-crypto'
import { type PropsWithChildren, type ReactElement, useState } from 'react'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'

import { useClassicChat } from './useClassicChat'

jest.mock('@/api/conversations', () => ({
    cancelConversation: jest.fn(),
    getConversation: jest.fn(),
    streamConversation: jest.fn(),
}))
jest.mock('@/api/sse', () => ({ readSse: jest.fn() }))
jest.mock('expo-crypto', () => ({ randomUUID: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))
jest.mock('@/features/chats/hooks', () => ({
    sessionListKeys: { all: () => [] },
    conversationListKeys: { all: () => [] },
}))

function wrapper({ children }: PropsWithChildren): ReactElement {
    const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } }))
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('classic chat transport', () => {
    beforeEach(() => {
        jest.resetAllMocks()
        let id = 0
        jest.mocked(randomUUID).mockImplementation(() => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`)
        jest.mocked(streamConversation).mockResolvedValue({} as Response)
        jest.mocked(getConversation).mockResolvedValue({
            messages: [],
            title: 'A chat',
            pending_approvals: [],
        } as unknown as Awaited<ReturnType<typeof getConversation>>)
        jest.mocked(readSse).mockResolvedValue()
    })

    test('sends new and subsequent turns to the same classic conversation', async () => {
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        await act(async () => {
            expect(await result.current.send('First')).toBe(true)
        })
        const first = jest.mocked(streamConversation).mock.calls[0]?.[0]
        expect(first).toMatchObject({ content: 'First', is_sandbox: false })
        await act(async () => {
            await result.current.send('Second')
        })
        expect(jest.mocked(streamConversation).mock.calls[1]?.[0]).toMatchObject({
            conversation: first?.conversation,
            content: 'Second',
            is_sandbox: false,
        })
    })

    test('blocks double submission and removes an undelivered optimistic message', async () => {
        let reject!: (error: Error) => void
        jest.mocked(streamConversation).mockReturnValue(
            new Promise((_resolve, rejectPromise) => {
                reject = rejectPromise
            })
        )
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let pending!: Promise<boolean>
        act(() => {
            pending = result.current.send('Keep this draft')
        })
        await act(async () => {
            expect(await result.current.send('Duplicate')).toBe(false)
        })
        await act(async () => {
            reject(new ApiError(429, { detail: 'Try later' }))
            expect(await pending).toBe(false)
        })
        expect(streamConversation).toHaveBeenCalledTimes(1)
        expect(result.current.state.messages).toEqual([])
        expect(result.current.error).toBe('Try later')
        expect(result.current.working).toBe(false)
    })

    test('ignores frames and completion from a conversation reset during streaming', async () => {
        let finish!: () => void
        jest.mocked(readSse).mockImplementation(
            (_response, onEvent) =>
                new Promise<void>((resolve) => {
                    finish = () => {
                        onEvent({
                            event: 'message',
                            data: JSON.stringify({ id: 'old', type: 'ai', content: 'Old answer' }),
                        })
                        resolve()
                    }
                })
        )
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let pending!: Promise<boolean>
        await act(async () => {
            pending = result.current.send('Old question')
            await Promise.resolve()
        })
        act(() => result.current.reset())
        await act(async () => {
            finish()
            await pending
        })
        expect(result.current.id).toBeNull()
        expect(result.current.state.messages).toEqual([])
    })

    test('offers history recovery after an accepted stream disconnects', async () => {
        jest.mocked(readSse).mockRejectedValueOnce(new TypeError('Connection lost'))
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        await act(async () => {
            expect(await result.current.send('Question')).toBe(true)
        })
        expect(result.current.historyError).toContain('Reconnect')
        await act(async () => result.current.reload())
        expect(result.current.historyError).toBeNull()
        expect(getConversation).toHaveBeenCalledWith(result.current.id, expect.any(AbortSignal))
    })

    test('guards duplicate cancellation requests', async () => {
        let finish!: () => void
        jest.mocked(cancelConversation).mockImplementation(
            () =>
                new Promise<void>((resolve) => {
                    finish = resolve
                })
        )
        const { result } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
        await act(async () => undefined)
        let pending!: Promise<void>
        act(() => {
            pending = result.current.stop()
        })
        await act(async () => result.current.stop())
        expect(cancelConversation).toHaveBeenCalledTimes(1)
        await act(async () => {
            finish()
            await pending
        })
        expect(result.current.stopping).toBe(false)
    })
})
