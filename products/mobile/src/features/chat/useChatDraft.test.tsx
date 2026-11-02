import { act, renderHook, waitFor } from '@testing-library/react-native'

const mockAuth = { signedIn: true, host: 'https://example.com', user: { uuid: 'user-1' }, projectId: 1 }
let mockStorageUnavailable = false
let mockWriteGate: Promise<void> | undefined
let mockWriteFailure = false
const mockValues = new Map<string, string>()

jest.mock('@/auth/authStore', () => ({
    useAuthStore: (selector: (state: typeof mockAuth) => unknown) => selector(mockAuth),
}))
jest.mock('./draftPersistence', () => {
    const { DraftStore } = jest.requireActual<typeof import('./draftStore')>('./draftStore')
    return {
        draftIdentity: () => JSON.stringify([mockAuth.host, mockAuth.user.uuid, mockAuth.projectId]),
        draftScope: async () => {
            if (mockStorageUnavailable) {
                throw new Error('Device storage unavailable')
            }
            return `scope-${mockAuth.projectId}`
        },
        chatDrafts: new DraftStore({
            getItem: async (key: string) => mockValues.get(key) ?? null,
            setItem: async (key: string, value: string) => {
                await mockWriteGate
                if (mockWriteFailure) throw new Error('Device full')
                mockValues.set(key, value)
            },
            removeItem: async (key: string) => {
                mockValues.delete(key)
            },
        }),
    }
})

import { chatDrafts } from './draftPersistence'
import { queueActions } from './messageQueue'
import { useChatDraft } from './useChatDraft'

beforeEach(async () => {
    mockAuth.projectId = 1
    mockStorageUnavailable = false
    mockWriteGate = undefined
    mockWriteFailure = false
    await chatDrafts.clear(['scope-1', 'scope-2'])
    mockValues.clear()
})

describe('chat draft persistence', () => {
    it('flushes on close inside the debounce window and restores text and reports on reopen', async () => {
        const hook = renderHook(() => useChatDraft(null, 'report-1'))
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        act(() => hook.result.current.change({ text: 'Draft', reportIds: ['report-1', 'report-2'] }))
        hook.unmount()
        const reopened = renderHook(() => useChatDraft(null, 'report-1'))
        await waitFor(() => expect(reopened.result.current.ready).toBe(true))
        expect(reopened.result.current.draft).toEqual({ text: 'Draft', reportIds: ['report-1', 'report-2'] })
        reopened.unmount()
    })

    it('keeps text typed while sending and follows task adoption without consuming the next new-chat slot', async () => {
        const hook = renderHook(({ taskId }: { taskId: string | null }) => useChatDraft(taskId, undefined), {
            initialProps: { taskId: null },
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let settle!: (sent: boolean) => Promise<void>
        await act(async () => {
            settle = await hook.result.current.beginSend({ text: 'First', reportIds: [] })
        })
        act(() => hook.result.current.change({ text: 'Next question', reportIds: [] }))
        hook.rerender({ taskId: 'task-1' })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        await act(async () => {
            await settle(true)
        })
        expect(hook.result.current.draft.text).toBe('Next question')
        hook.rerender({ taskId: null })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        expect(hook.result.current.draft.text).toBe('')
        act(() => hook.result.current.change({ text: 'New chat', reportIds: [] }))
        hook.unmount()
        expect(await chatDrafts.load('scope-1', 'task:task-1')).toEqual({ text: 'Next question', reportIds: [] })
        expect(await chatDrafts.load('scope-1', 'new-chat')).toEqual({ text: 'New chat', reportIds: [] })
    })

    it('an accepted send from a closed composer does not clear the reopened new-chat draft', async () => {
        const first = renderHook(() => useChatDraft(null, undefined))
        await waitFor(() => expect(first.result.current.ready).toBe(true))
        let settle!: (sent: boolean) => Promise<void>
        await act(async () => {
            settle = await first.result.current.beginSend({ text: 'Accepted', reportIds: [] })
        })
        first.unmount()
        const reopened = renderHook(() => useChatDraft(null, undefined))
        await waitFor(() => expect(reopened.result.current.ready).toBe(true))
        act(() => reopened.result.current.change({ text: 'Another question', reportIds: [] }))
        await act(async () => {
            await settle(true)
        })
        expect(reopened.result.current.draft.text).toBe('Another question')
        reopened.unmount()
        expect(await chatDrafts.load('scope-1', 'new-chat')).toEqual({ text: 'Another question', reportIds: [] })
    })

    it('does not restore an old failed send into another task in the same project', async () => {
        const hook = renderHook(({ taskId }: { taskId: string }) => useChatDraft(taskId, undefined), {
            initialProps: { taskId: 'task-1' },
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let settle!: (sent: boolean) => Promise<void>
        await act(async () => {
            settle = await hook.result.current.beginSend({ text: 'Unsent', reportIds: [] })
        })
        hook.rerender({ taskId: 'task-2' })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        await act(async () => {
            await settle(false)
        })
        expect(hook.result.current.draft.text).toBe('')
        expect(await chatDrafts.load('scope-1', 'task:task-1')).toEqual({ text: 'Unsent', reportIds: [] })
        hook.unmount()
    })

    it('keeps a failed new chat in its composer and leaves the send recoverable on project switch', async () => {
        const hook = renderHook(() => useChatDraft(null, undefined))
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let settle!: (sent: boolean) => Promise<void>
        await act(async () => {
            settle = await hook.result.current.beginSend({ text: 'Try again', reportIds: [] })
        })
        await act(async () => {
            await settle(false)
        })
        expect(hook.result.current.draft.text).toBe('Try again')
        await act(async () => {
            settle = await hook.result.current.beginSend({ text: 'Still pending', reportIds: [] })
        })
        mockAuth.projectId = 2
        hook.rerender({})
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        await act(async () => {
            await settle(false)
        })
        expect(hook.result.current.draft.text).toBe('')
        hook.unmount()
    })

    it('does not restore into another task when encrypted storage was unavailable', async () => {
        mockStorageUnavailable = true
        const hook = renderHook(({ taskId }: { taskId: string }) => useChatDraft(taskId, undefined), {
            initialProps: { taskId: 'task-1' },
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let settle!: (sent: boolean) => Promise<void>
        await act(async () => {
            settle = await hook.result.current.beginSend({ text: 'Unsent', reportIds: [] })
        })
        hook.rerender({ taskId: 'task-2' })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        await act(async () => {
            await settle(false)
        })
        expect(hook.result.current.draft.text).toBe('')
        hook.unmount()
    })
    it('commits queued text before clearing the composer and restores it held after reopening', async () => {
        const hook = renderHook(() => useChatDraft('task-1', undefined))
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        act(() => hook.result.current.change({ text: 'Keep this', reportIds: [] }))
        let finish!: () => void
        mockWriteGate = new Promise<void>((resolve) => {
            finish = resolve
        })
        let queued!: Promise<boolean>
        act(() => {
            queued = hook.result.current.updateQueue(queueActions.enqueue('Keep this'), true)
        })
        expect(hook.result.current.draft.text).toBe('Keep this')
        act(() => hook.result.current.change({ text: 'New typing', reportIds: [] }))
        await act(async () => {
            finish()
            await queued
        })
        expect(hook.result.current.draft.text).toBe('New typing')
        hook.unmount()
        const reopened = renderHook(() => useChatDraft('task-1', undefined))
        await waitFor(() => expect(reopened.result.current.ready).toBe(true))
        expect(reopened.result.current.queue).toMatchObject({ rows: [{ text: 'Keep this' }], hold: 'unconfirmed' })
        expect(reopened.result.current.draft.text).toBe('New typing')
        reopened.unmount()
    })

    it('keeps the composer when the queue write fails and allows an explicit retry', async () => {
        const hook = renderHook(() => useChatDraft('task-1', undefined))
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        act(() => hook.result.current.change({ text: 'Not saved', reportIds: [] }))
        mockWriteFailure = true
        await act(async () => {
            expect(await hook.result.current.updateQueue(queueActions.enqueue('Not saved'), true)).toBe(false)
        })
        expect(hook.result.current.draft.text).toBe('Not saved')
        expect(hook.result.current.queue.rows).toEqual([])
        expect(hook.result.current.queueError).toBeDefined()
        mockWriteFailure = false
        await act(async () => {
            expect(await hook.result.current.updateQueue(queueActions.enqueue('Not saved'), true)).toBe(true)
        })
        expect(hook.result.current.draft.text).toBe('')
        expect(hook.result.current.queue.rows).toHaveLength(1)
        hook.unmount()
    })

    it('does not hydrate a previous chat after switching destinations during a queue write', async () => {
        const hook = renderHook(({ taskId }: { taskId: string }) => useChatDraft(taskId, undefined), {
            initialProps: { taskId: 'task-1' },
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let finish!: () => void
        mockWriteGate = new Promise<void>((resolve) => {
            finish = resolve
        })
        let queued!: Promise<boolean>
        act(() => {
            queued = hook.result.current.updateQueue(queueActions.enqueue('First chat'), true)
        })
        hook.rerender({ taskId: 'task-2' })
        await act(async () => {
            finish()
            await queued
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        expect(hook.result.current.queue.rows).toEqual([])
        hook.rerender({ taskId: 'task-1' })
        await waitFor(() => expect(hook.result.current.queue.rows).toHaveLength(1))
        expect(hook.result.current.queue.hold).toBe('unconfirmed')
        hook.unmount()
    })
    it('keeps queued files live while a new chat adopts its task', async () => {
        const hook = renderHook(({ taskId }: { taskId: string | null }) => useChatDraft(taskId, undefined), {
            initialProps: { taskId: null },
        })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        const file = {
            id: 'file-1',
            uri: 'file:///example',
            name: 'example.txt',
            size: 1,
            contentType: 'text/plain',
            isImage: false,
        }
        await act(async () => {
            await hook.result.current.updateQueue(queueActions.enqueue('With a file', [file]), true)
        })
        hook.rerender({ taskId: 'created-task' })
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        expect(hook.result.current.queue.rows[0]?.attachments).toEqual([file])
        expect(hook.result.current.queue.rows[0]?.missingAttachments).toBeUndefined()
        expect((await chatDrafts.loadQueue('scope-1', 'new-chat')).rows).toEqual([])
        hook.unmount()
        const reopened = renderHook(() => useChatDraft('created-task', undefined))
        await waitFor(() => expect(reopened.result.current.ready).toBe(true))
        expect(reopened.result.current.queue.rows[0]).toMatchObject({ attachments: [], missingAttachments: 1 })
        reopened.unmount()
    })

    it('holds a queue even when Stop races its device write', async () => {
        const hook = renderHook(() => useChatDraft('task-1', undefined))
        await waitFor(() => expect(hook.result.current.ready).toBe(true))
        let finish!: () => void
        mockWriteGate = new Promise<void>((resolve) => {
            finish = resolve
        })
        let queued!: Promise<boolean>
        let stopped!: Promise<boolean>
        act(() => {
            queued = hook.result.current.updateQueue(queueActions.enqueue('Wait'), true)
            stopped = hook.result.current.updateQueue(queueActions.hold('cancelled'))
        })
        await act(async () => {
            finish()
            await queued
            await stopped
        })
        expect(hook.result.current.queue.hold).toBe('cancelled')
        hook.unmount()
    })
})
