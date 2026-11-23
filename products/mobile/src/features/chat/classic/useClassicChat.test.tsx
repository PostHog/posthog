import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import { randomUUID } from 'expo-crypto'
import { type PropsWithChildren, type ReactElement, useState } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'
import { REQUEST_TIMEOUT_MS } from '@/api/transport'
import { useProjectScope } from '@/auth/useProjectScope'
import { currentAiIdentity, useAiApproval } from '@/features/ai/aiApproval'

import { useClassicChat } from './useClassicChat'

jest.mock('@/api/conversations', () => ({
    cancelConversation: jest.fn(),
    getConversation: jest.fn(),
    streamConversation: jest.fn(),
}))
jest.mock('@/features/ai/aiApproval', () => ({ currentAiIdentity: jest.fn(), useAiApproval: jest.fn() }))
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
    let changeAppState: (state: AppStateStatus) => void
    beforeEach(() => {
        jest.resetAllMocks()
        AppState.currentState = 'active'
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
            changeAppState = listener
            return { remove: jest.fn() }
        })
        jest.mocked(useProjectScope).mockReturnValue(null)
        jest.mocked(currentAiIdentity).mockReturnValue('origin-project')
        const approval = { request: jest.fn(async () => true), pending: false, signal: new AbortController().signal }
        jest.mocked(useAiApproval).mockReturnValue(approval)
        let id = 0
        jest.mocked(randomUUID).mockImplementation(() => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`)
        jest.mocked(streamConversation).mockResolvedValue({} as Response)
        jest.mocked(getConversation).mockResolvedValue({
            messages: [],
            title: 'A chat',
            status: 'idle',
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

    test('keeps an unaccepted first send retryable after backgrounding', async () => {
        jest.mocked(streamConversation).mockImplementationOnce(
            (_body, signal) =>
                new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new Error('Aborted'))))
        )
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let sending!: Promise<boolean>
        await act(async () => {
            sending = result.current.send('Unsent question')
        })
        jest.mocked(getConversation).mockRejectedValueOnce(new ApiError(404, undefined))
        await act(async () => {
            changeAppState('background')
            expect(await sending).toBe(false)
            changeAppState('active')
        })
        expect(result.current.historyError).toBeNull()
        expect(result.current.id).toBeNull()
        expect(result.current.state.messages).toEqual([])
        expect(result.current.loading).toBe(false)
        expect(result.current.working).toBe(false)
        await act(async () => {
            expect(await result.current.send('Retry question')).toBe(true)
        })
    })

    test('retains uncheckpointed reply text when both reattachments fail', async () => {
        jest.useFakeTimers()
        jest.mocked(readSse).mockImplementationOnce(async (_response, onEvent) => {
            onEvent({
                event: 'message',
                data: JSON.stringify({ id: 'temp-reply', type: 'ai', content: 'Partial answer' }),
            })
            throw new TypeError('Disconnected')
        })
        jest.mocked(getConversation).mockResolvedValue({
            id: 'saved-chat',
            title: 'A chat',
            status: 'in_progress',
            messages: [],
            pending_approvals: [],
        } as unknown as Awaited<ReturnType<typeof getConversation>>)
        jest.mocked(streamConversation)
            .mockResolvedValueOnce({} as Response)
            .mockRejectedValue(new TypeError('Offline'))
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let sending!: Promise<boolean>
        await act(async () => {
            sending = result.current.send('Question')
        })
        expect(result.current.state.messages.some((message) => message.data.content === 'Partial answer')).toBe(true)
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1000)
            await sending
        })
        expect(result.current.historyError).not.toBeNull()
        expect(result.current.state.messages.some((message) => message.data.content === 'Partial answer')).toBe(true)
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
        await waitFor(() => expect(readSse).toHaveBeenCalled())
        await act(async () => {
            finish()
            await pending
        })
        expect(result.current.id).toBeNull()
        expect(result.current.state.messages).toEqual([])
    })

    test.each(['manual', 'foreground'] as const)('recovers a disconnected reply on %s', async (trigger) => {
        jest.useFakeTimers()
        jest.mocked(readSse).mockRejectedValueOnce(new TypeError('Connection lost'))
        jest.mocked(getConversation)
            .mockRejectedValueOnce(new TypeError('Connection lost'))
            .mockRejectedValueOnce(new TypeError('Connection lost'))
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let sending!: Promise<boolean>
        await act(async () => {
            sending = result.current.send('Question')
        })
        expect(result.current.historyError).toBeNull()
        expect(getConversation).toHaveBeenCalledTimes(1)
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1000)
            expect(await sending).toBe(true)
        })
        expect(getConversation).toHaveBeenCalledTimes(2)
        expect(result.current.historyError).toContain('Reconnect')
        await act(async () => {
            if (trigger === 'manual') await result.current.reload()
            else {
                changeAppState('background')
                changeAppState('active')
            }
        })
        expect(result.current.historyError).toBeNull()
        expect(getConversation).toHaveBeenCalledWith(result.current.id, expect.any(AbortSignal))
    })

    test('restarts interrupted history loading on return and ignores its late response', async () => {
        let finish!: (value: Awaited<ReturnType<typeof getConversation>>) => void
        jest.mocked(getConversation).mockReturnValueOnce(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        const { result } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
        const signal = jest.mocked(getConversation).mock.calls[0]?.[1]
        await act(async () => {
            changeAppState('inactive')
            changeAppState('background')
            changeAppState('active')
        })
        expect(signal?.aborted).toBe(true)
        expect(getConversation).toHaveBeenCalledTimes(2)
        expect(result.current.loading).toBe(false)
        expect(result.current.state.title).toBe('A chat')
        await act(async () =>
            finish({ title: 'Stale', messages: [], pending_approvals: [] } as unknown as Awaited<
                ReturnType<typeof getConversation>
            >)
        )
        expect(result.current.state.title).toBe('A chat')
    })

    test.each([
        ['history', true],
        ['history', false],
        ['reattach', true],
        ['reattach', false],
    ] as const)(
        'keeps %s recovery silent until the second attempt settles (success: %s)',
        async (boundary, succeeds) => {
            jest.useFakeTimers()
            const saved = {
                id: 'saved-chat',
                title: 'A chat',
                status: 'idle',
                messages: [{ id: 'reply', type: 'ai', content: 'Saved reply' }],
                pending_approvals: [],
            } as unknown as Awaited<ReturnType<typeof getConversation>>
            const { result } = renderHook(() => useClassicChat(saved.id, saved), { wrapper })
            let settle!: () => void
            const pending = new Promise<never>((_resolve, reject) => {
                settle = () => reject(new TypeError('Connection lost'))
            })
            if (boundary === 'history') {
                jest.mocked(getConversation).mockRejectedValueOnce(new TypeError('Connection lost'))
                if (succeeds) jest.mocked(getConversation).mockResolvedValueOnce(saved)
                else jest.mocked(getConversation).mockReturnValueOnce(pending)
            } else {
                jest.mocked(getConversation).mockResolvedValue({ ...saved, status: 'in_progress' })
                jest.mocked(streamConversation).mockRejectedValueOnce(new TypeError('Connection lost'))
                if (!succeeds) jest.mocked(streamConversation).mockReturnValueOnce(pending)
            }
            await act(async () => {
                changeAppState('background')
                changeAppState('active')
            })
            expect(result.current.historyError).toBeNull()
            expect(result.current.error).toBeNull()
            expect(result.current.state.messages[0]?.data.content).toBe('Saved reply')
            await act(async () => {
                await jest.advanceTimersByTimeAsync(999)
            })
            expect(boundary === 'history' ? getConversation : streamConversation).toHaveBeenCalledTimes(1)
            await act(async () => {
                await jest.advanceTimersByTimeAsync(1)
            })
            expect(result.current.historyError).toBeNull()
            expect(result.current.error).toBeNull()
            if (!succeeds) {
                await act(async () => settle())
                expect(result.current.historyError).not.toBeNull()
                expect(boundary === 'history' ? getConversation : streamConversation).toHaveBeenCalledTimes(2)
            }
            expect(result.current.working).toBe(false)
            expect(result.current.loading).toBe(false)
            expect(
                jest
                    .mocked(streamConversation)
                    .mock.calls.every(([body]) => body.content === null && !body.resume_payload)
            ).toBe(true)
            expect(cancelConversation).not.toHaveBeenCalled()
        }
    )

    test.each(['background', 'reset', 'unmount'] as const)(
        'cancels a delayed recovery retry on %s',
        async (transition) => {
            jest.useFakeTimers()
            jest.mocked(getConversation).mockRejectedValue(new TypeError('Offline'))
            const { result, unmount } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
            await act(async () => undefined)
            expect(getConversation).toHaveBeenCalledTimes(1)
            await act(async () => {
                if (transition === 'background') changeAppState('background')
                else if (transition === 'reset') result.current.reset()
                else unmount()
            })
            await act(async () => {
                await jest.advanceTimersByTimeAsync(1000)
            })
            expect(getConversation).toHaveBeenCalledTimes(1)
            expect(result.current.historyError).toBeNull()
        }
    )

    test.each([401, 403, 404])('does not silently retry a %s history rejection', async (status) => {
        jest.useFakeTimers()
        jest.mocked(getConversation).mockRejectedValue(new ApiError(status, undefined))
        const { result } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
        await act(async () => undefined)
        expect(result.current.historyError).not.toBeNull()
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1000)
        })
        expect(getConversation).toHaveBeenCalledTimes(1)
    })

    test.each(['reset', 'project', 'unmount'] as const)('does not reconnect a chat after %s', async (transition) => {
        const { result, unmount } = renderHook(() => useClassicChat('saved-chat'), { wrapper })
        await act(async () => undefined)
        await act(async () => changeAppState('background'))
        if (transition === 'reset') act(() => result.current.reset())
        else if (transition === 'project') jest.mocked(currentAiIdentity).mockReturnValue('other-project')
        else unmount()
        await act(async () => changeAppState('active'))
        expect(getConversation).toHaveBeenCalledTimes(1)
        expect(streamConversation).not.toHaveBeenCalled()
    })

    test.each(['idle', 'in_progress', 'approval', 'form'] as const)(
        'recovers a backgrounded reply with %s history without resending or canceling it',
        async (status) => {
            let finish!: () => void
            jest.mocked(readSse).mockImplementationOnce(
                (_response, onEvent) =>
                    new Promise<void>((resolve) => {
                        onEvent({
                            event: 'message',
                            data: JSON.stringify({ id: 'partial', type: 'ai', content: 'Checking.' }),
                        })
                        finish = () => {
                            onEvent({
                                event: 'message',
                                data: JSON.stringify({ id: 'stale', type: 'ai', content: 'Stale reply' }),
                            })
                            resolve()
                        }
                    })
            )
            const { result } = renderHook(() => useClassicChat(), { wrapper })
            let sending!: Promise<boolean>
            await act(async () => {
                sending = result.current.send('Question')
            })
            const conversation = result.current.id
            const signal = jest.mocked(readSse).mock.calls[0]?.[2]
            await act(async () => changeAppState('background'))
            expect(signal?.aborted).toBe(true)
            expect(result.current.state.messages.at(-1)?.data.content).toBe('Checking.')
            expect(result.current.historyError).toBeNull()
            expect(getConversation).not.toHaveBeenCalled()

            const saved = {
                id: conversation,
                messages: [
                    {
                        id: 'reply',
                        type: 'ai',
                        content: 'Saved reply',
                        ...(status === 'form'
                            ? {
                                  tool_calls: [
                                      {
                                          id: 'form-call',
                                          name: 'create_form',
                                          args: {
                                              questions: [
                                                  {
                                                      id: 'q1',
                                                      title: 'Scope',
                                                      question: 'Which events?',
                                                      options: [{ value: 'All' }],
                                                  },
                                              ],
                                          },
                                      },
                                  ],
                              }
                            : {}),
                    },
                ],
                title: 'A chat',
                status: status === 'idle' ? 'idle' : 'in_progress',
                pending_approvals:
                    status === 'approval' ? [{ proposal_id: 'proposal-1', decision_status: 'pending' }] : [],
            } as unknown as Awaited<ReturnType<typeof getConversation>>
            jest.mocked(getConversation).mockResolvedValue(saved)
            jest.mocked(readSse).mockReturnValueOnce(new Promise(() => undefined))
            await act(async () => {
                changeAppState('active')
                changeAppState('active')
            })
            expect(getConversation).toHaveBeenCalledTimes(1)
            expect(result.current.state.messages.at(-1)?.data.content).toBe('Saved reply')
            expect(result.current.historyError).toBeNull()
            expect(result.current.working).toBe(status === 'in_progress')
            expect(streamConversation).toHaveBeenCalledTimes(status === 'in_progress' ? 2 : 1)
            if (status === 'in_progress')
                expect(jest.mocked(streamConversation).mock.lastCall?.[0]).toMatchObject({
                    conversation,
                    content: null,
                })
            expect(cancelConversation).not.toHaveBeenCalled()
            await act(async () => {
                finish()
                await sending
            })
            expect(result.current.state.messages.at(-1)?.data.content).toBe('Saved reply')
        }
    )

    test('ignores recovered history after starting a new chat', async () => {
        let recover!: (saved: Awaited<ReturnType<typeof getConversation>>) => void
        jest.mocked(readSse).mockRejectedValueOnce(new TypeError('Connection lost'))
        jest.mocked(getConversation).mockReturnValueOnce(
            new Promise((resolve) => {
                recover = resolve
            })
        )
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let pending!: Promise<boolean>
        await act(async () => {
            pending = result.current.send('Question')
            await Promise.resolve()
        })
        await waitFor(() => expect(getConversation).toHaveBeenCalledTimes(1))
        act(() => result.current.reset())
        await act(async () => {
            recover({
                messages: [{ id: 'reply-1', type: 'ai', content: 'Old reply' }],
                title: 'Old chat',
                status: 'idle',
                pending_approvals: [],
            } as unknown as Awaited<ReturnType<typeof getConversation>>)
            await pending
        })
        expect(result.current.id).toBeNull()
        expect(result.current.state.messages).toEqual([])
        expect(result.current.historyError).toBeNull()
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
    test.each(['idle', 'in_progress', 'unavailable'] as const)(
        'checks saved history after an accepted stream stalls with %s history',
        async (status) => {
            jest.useFakeTimers()
            const saved = {
                messages: [
                    { id: 'human-1', type: 'human', content: 'Question' },
                    { id: 'reply-1', type: 'ai', content: 'Saved reply' },
                ],
                title: 'A chat',
                status,
                pending_approvals: [],
            } as unknown as Awaited<ReturnType<typeof getConversation>>
            if (status === 'unavailable')
                jest.mocked(getConversation)
                    .mockRejectedValueOnce(new TypeError('Offline'))
                    .mockRejectedValueOnce(new TypeError('Offline'))
            else
                jest.mocked(getConversation)
                    .mockResolvedValueOnce(saved)
                    .mockResolvedValueOnce({ ...saved, status: 'idle' })
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
                await jest.advanceTimersByTimeAsync(1000)
                expect(await pending).toBe(true)
            })
            expect(result.current.working).toBe(false)
            expect(streamConversation).toHaveBeenCalledTimes(status === 'in_progress' ? 2 : 1)
            expect(getConversation).toHaveBeenCalledTimes(status === 'idle' ? 1 : 2)
            if (status !== 'unavailable') {
                expect(result.current.historyError).toBeNull()
                expect(result.current.state.messages.at(-1)?.data.content).toBe('Saved reply')
            } else {
                expect(result.current.historyError).toContain('Reconnect')
                expect(result.current.state.messages[0]?.data.content).toBe('Question')
            }
            expect(reader.cancel).toHaveBeenCalled()
            await act(async () => result.current.reload())
            expect(result.current.historyError).toBeNull()
        }
    )
    test.each(['stream', 'history', 'snapshot'])(
        'exposes and resumes forms from %s without reconnecting or duplicating submissions',
        async (source) => {
            jest.useFakeTimers()
            const form = {
                id: 'form-call',
                name: 'create_form',
                args: {
                    questions: [{ id: 'q1', title: 'Scope', question: 'Which events?', options: [{ value: 'All' }] }],
                },
            }
            const message = { id: 'form-message', type: 'ai', content: '', tool_calls: [form] }
            const saved = {
                id: 'saved-chat',
                messages: [message],
                title: 'A chat',
                pending_approvals: [],
                status: 'in_progress',
            } as unknown as Awaited<ReturnType<typeof getConversation>>
            if (source === 'history') jest.mocked(getConversation).mockResolvedValueOnce(saved)
            const { result } = renderHook(
                () =>
                    useClassicChat(
                        source === 'stream' ? undefined : 'saved-chat',
                        source === 'snapshot' ? saved : undefined
                    ),
                { wrapper }
            )
            await act(async () => undefined)
            if (source === 'stream') {
                jest.mocked(readSse).mockImplementationOnce(async (_response, onEvent) => {
                    onEvent({ event: 'message', data: JSON.stringify(message) })
                })
                jest.mocked(getConversation)
                    .mockRejectedValueOnce(new Error('Connection lost'))
                    .mockRejectedValueOnce(new Error('Connection lost'))
                    .mockRejectedValueOnce(new Error('Connection lost'))
                let sending!: Promise<boolean>
                await act(async () => {
                    sending = result.current.send('Question')
                })
                await act(async () => {
                    await jest.advanceTimersByTimeAsync(1000)
                    await sending
                })
            } else {
                expect(streamConversation).not.toHaveBeenCalled()
            }
            expect(result.current.form).toEqual({ id: 'form-call', questions: form.args.questions })
            jest.mocked(streamConversation).mockClear()
            let finish!: (response: Response) => void
            jest.mocked(streamConversation).mockReturnValueOnce(
                new Promise((resolve) => {
                    finish = resolve
                })
            )
            let pending!: Promise<boolean>
            act(() => {
                pending = result.current.submitForm({ q1: ['All', 'Custom'] })
            })
            await act(async () => {
                expect(await result.current.dismissForm()).toBe(false)
            })
            expect(streamConversation).toHaveBeenCalledTimes(1)
            expect(jest.mocked(streamConversation).mock.lastCall?.[0]).toMatchObject({
                content: null,
                resume_payload: { action: 'form', form_answers: { q1: ['All', 'Custom'] } },
            })
            await act(async () => {
                finish({} as Response)
                await pending
            })
            expect(result.current.form).toBeNull()
            jest.mocked(getConversation).mockResolvedValueOnce(saved)
            await act(async () => result.current.reload())
            await act(async () => {
                expect(await result.current.dismissForm()).toBe(true)
            })
            expect(jest.mocked(streamConversation).mock.lastCall?.[0]).toMatchObject({
                content: null,
                resume_payload: { action: 'dismiss_form' },
            })
            expect(result.current.form).toBeNull()
            expect(result.current.state.messages).toEqual([])
        }
    )

    test.each(['send', 'approve', 'reject'] as const)('checks AI approval before %s', async (action) => {
        const saved = {
            id: 'saved-chat',
            title: 'Saved chat',
            status: 'idle',
            messages: [{ id: 'human-1', type: 'human', content: 'Show my events' }],
            pending_approvals: [{ proposal_id: 'proposal-1', decision_status: 'pending', tool_name: 'Update insight' }],
        } as unknown as Awaited<ReturnType<typeof getConversation>>
        const { result } = renderHook(() => useClassicChat(saved.id, saved), { wrapper })
        const approval = jest.mocked(useAiApproval).mock.results[0]?.value as ReturnType<typeof useAiApproval>
        jest.mocked(approval.request).mockResolvedValueOnce(false)
        await act(async () => {
            expect(
                await (action === 'send'
                    ? result.current.send('Question')
                    : result.current.answer(action === 'approve'))
            ).toBe(false)
        })
        expect(streamConversation).not.toHaveBeenCalled()
        expect(result.current.working).toBe(false)
        expect(result.current.state.messages[0]?.data.content).toBe('Show my events')
        expect(getConversation).not.toHaveBeenCalled()
    })

    test.each(['unmount', 'project'] as const)('ignores a prepared send after %s', async (transition) => {
        const { result, unmount } = renderHook(() => useClassicChat(), { wrapper })
        const send = result.current.send
        if (transition === 'unmount') unmount()
        else if (transition === 'project') jest.mocked(currentAiIdentity).mockReturnValue('other-project')
        await act(async () => {
            expect(await send('Question')).toBe(false)
        })
        expect(streamConversation).not.toHaveBeenCalled()
    })

    test.each(['unmount', 'project', 'reset'] as const)('abandons an approval check after %s', async (transition) => {
        let approve!: (value: boolean) => void
        const { result, unmount } = renderHook(() => useClassicChat(), { wrapper })
        const approval = jest.mocked(useAiApproval).mock.results[0]?.value as ReturnType<typeof useAiApproval>
        jest.mocked(approval.request).mockReturnValueOnce(
            new Promise((resolve) => {
                approve = resolve
            })
        )
        let sending!: Promise<boolean>
        act(() => {
            sending = result.current.send('Question')
        })
        if (transition === 'unmount') unmount()
        else if (transition === 'project') jest.mocked(currentAiIdentity).mockReturnValue('other-project')
        else act(() => result.current.reset())
        await act(async () => {
            approve(true)
            expect(await sending).toBe(false)
        })
        expect(streamConversation).not.toHaveBeenCalled()
    })

    test.each(['idle', 'in_progress'] as const)(
        'reuses loaded %s history and can explicitly reload',
        async (status) => {
            const saved = {
                id: 'saved-chat',
                title: 'Saved chat',
                status,
                messages: [{ id: 'message-1', type: 'human', content: 'Saved question' }],
                pending_approvals: [],
            } as unknown as Awaited<ReturnType<typeof getConversation>>
            let finish!: () => void
            jest.mocked(readSse).mockImplementation(
                () =>
                    new Promise((resolve) => {
                        finish = resolve
                    })
            )
            const { result } = renderHook(() => useClassicChat(saved.id, saved), { wrapper })
            expect(result.current.state.messages[0]?.data.content).toBe('Saved question')
            expect(result.current.loading).toBe(false)
            expect(getConversation).not.toHaveBeenCalled()
            if (status === 'in_progress') {
                await waitFor(() => expect(readSse).toHaveBeenCalled())
                expect(streamConversation).toHaveBeenCalledWith(
                    expect.objectContaining({ conversation: saved.id, content: null }),
                    expect.any(AbortSignal)
                )
                await act(async () => {
                    finish()
                })
            }
            await act(async () => {
                await result.current.reload()
            })
            expect(getConversation).toHaveBeenCalledWith(saved.id, expect.any(AbortSignal))
        }
    )
    test('reports acceptance before the reply finishes', async () => {
        let finish!: () => void
        jest.mocked(readSse).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finish = resolve
                })
        )
        const accepted = jest.fn(async () => undefined)
        const { result } = renderHook(() => useClassicChat(), { wrapper })
        let sending!: Promise<boolean>
        act(() => {
            sending = result.current.send('A question', accepted)
        })
        await waitFor(() => expect(readSse).toHaveBeenCalled())
        expect(accepted).toHaveBeenCalledTimes(1)
        expect(result.current.working).toBe(true)
        await act(async () => {
            finish()
            expect(await sending).toBe(true)
        })
    })
})
