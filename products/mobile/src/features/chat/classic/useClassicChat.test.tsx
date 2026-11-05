import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import { randomUUID } from 'expo-crypto'
import { type PropsWithChildren, type ReactElement, useState } from 'react'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'
import { REQUEST_TIMEOUT_MS } from '@/api/transport'
import { useProjectScope } from '@/auth/useProjectScope'

import { useClassicChat } from './useClassicChat'

jest.mock('@/api/conversations', () => ({
    cancelConversation: jest.fn(),
    getConversation: jest.fn(),
    streamConversation: jest.fn(),
}))
jest.mock('@/api/sse', () => ({ readSse: jest.fn() }))
jest.mock('expo-crypto', () => ({ randomUUID: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: jest.fn(() => null) }))
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
        jest.mocked(useProjectScope).mockReturnValue(null)
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

    afterEach(() => jest.useRealTimers())

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
    test.each(['persisted', 'transient'])(
        'retains a %s generation failure after history reconciliation',
        async (kind) => {
            const failure = {
                id: 'failure-1',
                type: 'ai/failure',
                content: 'Could not start this reply. Try again.',
            }
            jest.mocked(readSse).mockImplementation(async (_response, onEvent) => {
                onEvent({ event: 'message', data: JSON.stringify(failure) })
            })
            if (kind === 'persisted')
                jest.mocked(getConversation).mockResolvedValue({
                    messages: [failure],
                    title: 'A chat',
                    pending_approvals: [],
                } as unknown as Awaited<ReturnType<typeof getConversation>>)
            const { result } = renderHook(() => useClassicChat(), { wrapper })
            await act(async () => {
                await result.current.send('Question')
            })
            expect(result.current.error).toBe(failure.content)
            expect(result.current.working).toBe(false)
        }
    )

    test.each(['pending', 'approved', 'rejected', 'expired'])(
        'reconnects only when the %s approval needs no decision',
        async (decision_status) => {
            jest.mocked(getConversation).mockResolvedValue({
                messages: [],
                title: 'A chat',
                status: 'in_progress',
                pending_approvals: [{ proposal_id: 'proposal-1', decision_status }],
            } as unknown as Awaited<ReturnType<typeof getConversation>>)
            const { result } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
            await act(async () => undefined)
            expect(streamConversation).toHaveBeenCalledTimes(decision_status === 'pending' ? 0 : 1)
            expect(result.current.loading).toBe(false)
        }
    )

    test('releases a stalled connection and allows another send', async () => {
        jest.useFakeTimers()
        jest.mocked(streamConversation).mockReturnValueOnce(new Promise(() => undefined))
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let pending!: Promise<boolean>
        act(() => {
            pending = result.current.send('Question')
        })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
            expect(await pending).toBe(false)
        })
        expect(result.current.working).toBe(false)
        expect(result.current.error).toContain('too long')
        await act(async () => {
            expect(await result.current.send('Retry')).toBe(true)
        })
    })

    test.each(['history', 'stream', 'stop'])(
        'releases an in-flight %s when the conversation changes',
        async (phase) => {
            let finish!: () => void
            const stalled = new Promise<void>((resolve) => {
                finish = resolve
            })
            if (phase === 'history')
                jest.mocked(getConversation).mockImplementationOnce(async () => {
                    await stalled
                    return {
                        messages: [{ type: 'ai', content: 'Stale' }],
                        pending_approvals: [],
                    } as unknown as Awaited<ReturnType<typeof getConversation>>
                })
            if (phase === 'stream') jest.mocked(readSse).mockImplementationOnce(() => stalled)
            if (phase === 'stop') jest.mocked(cancelConversation).mockReturnValueOnce(stalled)
            const { result, rerender } = renderHook(({ id }: { id: string }) => useClassicChat(id), {
                wrapper,
                initialProps: { id: 'old-chat' },
            })
            let pending: Promise<unknown> = Promise.resolve()
            await act(async () => {
                if (phase === 'stream') pending = result.current.send('Old question')
                if (phase === 'stop') pending = result.current.stop()
            })
            await act(async () => rerender({ id: 'new-chat' }))
            expect(result.current.id).toBe('new-chat')
            expect(result.current.loading).toBe(false)
            expect(result.current.working).toBe(false)
            expect(result.current.stopping).toBe(false)
            await act(async () => {
                finish()
                await pending
            })
            expect(result.current.state.messages).toEqual([])
            await act(async () => {
                expect(await result.current.send('New question')).toBe(true)
            })
            expect(jest.mocked(streamConversation).mock.lastCall?.[0].conversation).toBe('new-chat')
        }
    )

    test('reloads history after the project changes during a request', async () => {
        jest.mocked(useProjectScope).mockReturnValue({ host: 'https://app.example.com', projectId: 1 })
        jest.mocked(getConversation).mockReturnValueOnce(new Promise(() => undefined))
        const { result, rerender } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
        jest.mocked(useProjectScope).mockReturnValue({ host: 'https://app.example.com', projectId: 2 })
        await act(async () => rerender({}))
        expect(result.current.loading).toBe(false)
        expect(getConversation).toHaveBeenCalledTimes(2)
        expect(result.current.state.title).toBe('A chat')
    })
    test('exposes recovery and releases the lock after an accepted stream stalls', async () => {
        jest.useFakeTimers()
        const reader = {
            read: () => new Promise(() => undefined),
            cancel: jest.fn(async () => undefined),
        }
        jest.mocked(streamConversation).mockResolvedValueOnce({
            body: { getReader: () => reader },
        } as unknown as Response)
        jest.mocked(readSse).mockImplementationOnce(jest.requireActual('@/api/sse').readSse)
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let pending!: Promise<boolean>
        await act(async () => {
            pending = result.current.send('Question')
            await Promise.resolve()
        })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(60_000)
            expect(await pending).toBe(true)
        })
        expect(result.current.working).toBe(false)
        expect(result.current.historyError).toContain('Reconnect')
        expect(reader.cancel).toHaveBeenCalled()
        await act(async () => result.current.reload())
        expect(result.current.historyError).toBeNull()
    })
})
