import { act, renderHook, waitFor } from '@testing-library/react-native'
import { AppState } from 'react-native'
import { ApiError } from '@/api/client'
import type { TaskApi, TaskCreateResponseApi, TaskRunApi } from '@/api/tasks'
import * as tasks from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'
import { getSessionTokens, setSessionTokens } from '@/auth/tokens'
import { useAiApproval } from '@/features/ai/aiApproval'
import { setAnalyticsClient } from '@/lib/analytics'

import type { PendingAttachment } from '../attachments/types'
import { AttachmentUploadError, uploadAttachments } from '../attachments/uploadAttachments'
import type { ChatRunOptions } from '../chatRunOptions'
import { chatPrompt } from '../contextPrompt'
import type { ChatContext } from '../types'
import { useSession } from './useSession'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/features/ai/aiApproval', () => ({
    useAiApproval: jest.fn(() => ({
        request: jest.fn(async () => true),
        pending: false,
        signal: new AbortController().signal,
    })),
}))
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/api/tasks', () => ({
    ...jest.requireActual<typeof import('@/api/tasks')>('@/api/tasks'),
    createTask: jest.fn(),
    deleteTask: jest.fn(() => Promise.resolve()),
    getTask: jest.fn(),
    getTaskRun: jest.fn(),
    getTaskRunLogs: jest.fn(),
    startTaskRun: jest.fn(),
    sendTaskRunCommand: jest.fn(),
    // The tests need no frames, so the connection stays open until the hook aborts it.
    openTaskRunStream: jest.fn(
        (_taskId: string, _runId: string, options: { signal?: AbortSignal }) =>
            new Promise<Response>((_resolve, reject) => {
                options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
            })
    ),
}))

jest.mock('../attachments/uploadAttachments', () => ({
    ...jest.requireActual<typeof import('../attachments/uploadAttachments')>('../attachments/uploadAttachments'),
    uploadAttachments: jest.fn(),
}))

const mocked = jest.mocked(tasks)
const upload = jest.mocked(uploadAttachments)
const SHOT: PendingAttachment = {
    id: 'pick-1',
    uri: 'file:///picked/shot.png',
    name: 'shot.png',
    size: 100,
    contentType: 'image/png',
    isImage: true,
}
const TASK_ID = 'task-1'

function run(overrides: Partial<TaskRunApi>): TaskRunApi {
    return {
        id: 'run-1',
        task: TASK_ID,
        status: 'completed',
        stage: null,
        branch: null,
        error_message: null,
        output: null,
        completed_at: null,
        ...overrides,
    }
}

function task(latest: TaskRunApi): TaskApi {
    return { id: TASK_ID, title: 'Fix the flaky checkout test', signal_report: null, latest_run: latest }
}

const DEFAULT_PLAN: ChatRunOptions = { model: 'default', permissionMode: 'plan' }
const DEFAULT_AUTO: ChatRunOptions = { model: 'default', permissionMode: 'auto' }

const OPUS_PLAN: ChatRunOptions = {
    model: { runtimeAdapter: 'claude', model: 'claude-opus-5-5', reasoningEffort: 'high' },
    permissionMode: 'plan',
}

const REPORT_CONTEXT: ChatContext = {
    kind: 'reports',
    reports: [{ reportId: 'rep-1', title: 'Checkout errors spike', canAct: false }],
}

function logLine(update: Record<string, unknown>): Record<string, unknown> {
    return { type: 'notification', notification: { method: 'session/update', params: { update } } }
}

/** A stream that stays open until the hook aborts it. */
function liveStream(caughtUp = true): {
    response: Response
    push: (frame: unknown, id?: string, event?: string) => void
} {
    const queue: Uint8Array[] = []
    let waiting: ((result: { value: Uint8Array | undefined; done: boolean }) => void) | null = null
    const reader = {
        read: () =>
            new Promise<{ value: Uint8Array | undefined; done: boolean }>((resolve) => {
                const next = queue.shift()
                if (next) {
                    resolve({ value: next, done: false })
                } else {
                    waiting = resolve
                }
            }),
        cancel: async (): Promise<void> => {
            waiting?.({ value: undefined, done: true })
        },
    }
    const push = (frame: unknown, id?: string, event = 'message'): void => {
        const chunk = new TextEncoder().encode(
            `${id ? `id: ${id}\n` : ''}event: ${event}\ndata: ${JSON.stringify(frame)}\n\n`
        )
        if (waiting) {
            const resolve = waiting
            waiting = null
            resolve({ value: chunk, done: false })
        } else {
            queue.push(chunk)
        }
    }
    if (caughtUp) {
        push({}, undefined, 'keepalive')
    }
    return { response: { ok: true, body: { getReader: () => reader } } as unknown as Response, push }
}

function sentCommands(): unknown[] {
    return mocked.sendTaskRunCommand.mock.calls.map(([, , command]) => command)
}

const LIVE_TOOL_CALL = logLine({
    sessionUpdate: 'tool_call',
    toolCallId: 'live-tool',
    title: 'Run regression tests',
    status: 'in_progress',
})

describe('useSession', () => {
    const originalAppState = AppState.currentState
    beforeEach(() => {
        AppState.currentState = 'active'
        jest.mocked(useAiApproval).mockReturnValue({
            request: jest.fn(async () => true),
            pending: false,
            signal: new AbortController().signal,
        })
        mocked.openTaskRunStream.mockReset().mockImplementation(
            (_taskId, _runId, options) =>
                new Promise<Response>((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                })
        )
    })
    afterEach(() => {
        AppState.currentState = originalAppState
        jest.clearAllMocks()
    })

    test.each([false, true])(
        'a denied AI approval prevents uploads and message delivery (existing task: %s)',
        async (existing) => {
            jest.mocked(useAiApproval).mockReturnValue({
                request: jest.fn(async () => false),
                pending: false,
                signal: new AbortController().signal,
            })
            mocked.getTask.mockResolvedValue(task(run({ status: 'completed' })))
            mocked.getTaskRunLogs.mockResolvedValue([])
            const { result, unmount } = renderHook(() => useSession(existing ? { taskId: TASK_ID } : {}))
            if (existing) await waitFor(() => expect(result.current.history.status).toBe('idle'))
            await act(async () => {
                await expect(
                    result.current.start('Explain this', { kind: 'none' }, DEFAULT_AUTO, { attachments: [SHOT] })
                ).resolves.toBe(false)
                await expect(result.current.send('Queued question', { kind: 'none' })).resolves.toBe(false)
            })
            expect(mocked.createTask).not.toHaveBeenCalled()
            expect(mocked.startTaskRun).not.toHaveBeenCalled()
            expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
            expect(upload).not.toHaveBeenCalled()
            expect(result.current.items).toEqual([])
            unmount()
        }
    )

    test.each(['keepalive', 'quiet', 'stream-end'])(
        'opening a chat publishes its backlog together on %s, then streams new messages',
        async (boundary) => {
            jest.useFakeTimers()
            const stream = liveStream(false)
            mocked.openTaskRunStream.mockResolvedValueOnce(stream.response)
            mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))
            mocked.getTaskRun.mockResolvedValue(run({ status: 'completed' }))
            const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
            try {
                await act(async () => {})
                expect(result.current.history.status).toBe('loading')
                await act(async () => {
                    stream.push(
                        logLine({ sessionUpdate: 'user_message_chunk', content: { text: 'Explain the chart' } }),
                        'log-0'
                    )
                    stream.push(logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'First ' } }), 'log-1')
                })
                await act(async () => {
                    jest.advanceTimersByTime(1000)
                })
                expect(result.current.history.status).toBe('loading')
                expect(result.current.items).toEqual([])
                await act(async () => {
                    stream.push(
                        logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'answer.' } }),
                        '100-0'
                    )
                    stream.push(
                        { type: 'notification', notification: { method: '_posthog/turn_complete', params: {} } },
                        '101-0'
                    )
                })
                expect(result.current.items).toEqual([])
                await act(async () => {
                    if (boundary === 'quiet') {
                        jest.advanceTimersByTime(250)
                    } else {
                        stream.push({}, undefined, boundary)
                    }
                })
                expect(result.current.history.status).toBe('idle')
                expect(result.current.items).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({ kind: 'user', text: 'Explain the chart' }),
                        expect.objectContaining({ kind: 'assistant', text: 'First answer.', complete: true }),
                    ])
                )
                expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
                if (boundary !== 'stream-end') {
                    await act(async () => {
                        stream.push(
                            logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'A new reply' } }),
                            '102-0'
                        )
                    })
                    expect(result.current.items.at(-1)).toMatchObject({
                        kind: 'assistant',
                        text: 'A new reply',
                        complete: false,
                    })
                }
            } finally {
                unmount()
                jest.useRealTimers()
            }
        }
    )

    test.each(['retry', 'completed'])(
        'interrupted catch-up preserves the whole history when the run is %s',
        async (outcome) => {
            jest.useFakeTimers()
            const interrupted = liveStream(false)
            const reconnected = liveStream(false)
            const first = {
                ...logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'Saved ' } }),
                event_id: 'first',
            }
            const last = {
                ...logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'reply.' } }),
                event_id: 'last',
            }
            mocked.openTaskRunStream
                .mockResolvedValueOnce(interrupted.response)
                .mockResolvedValueOnce(reconnected.response)
            mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))
            mocked.getTaskRun.mockResolvedValue(run({ status: outcome === 'completed' ? 'completed' : 'in_progress' }))
            mocked.getTaskRunLogs.mockResolvedValue([first, last])
            const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
            try {
                await act(async () => {})
                await act(async () => {
                    interrupted.push(first, 'log-0')
                })
                expect(result.current.items).toEqual([])
                await act(async () => {
                    interrupted.push({ error: 'Connection interrupted' }, undefined, 'error')
                })
                if (outcome === 'retry') {
                    expect(result.current.history.status).toBe('loading')
                    await act(async () => {
                        jest.advanceTimersByTime(2000)
                    })
                    expect(mocked.openTaskRunStream.mock.calls.at(-1)?.[2]?.lastEventId).toBe('log-0')
                    await act(async () => {
                        reconnected.push(last, 'log-1')
                        reconnected.push({}, undefined, 'keepalive')
                    })
                }
                expect(result.current.history.status).toBe('idle')
                expect(result.current.items).toEqual([
                    expect.objectContaining({ kind: 'assistant', text: 'Saved reply.' }),
                ])
            } finally {
                unmount()
                jest.useRealTimers()
            }
        }
    )

    test.each([false, true])('a full resync retains history already published: %s', async (published) => {
        const firstStream = liveStream(false)
        const secondStream = liveStream(false)
        const first = { ...logLine({ sessionUpdate: 'agent_message_chunk', text: 'Saved ' }), event_id: 'boot-1' }
        const last = { ...logLine({ sessionUpdate: 'agent_message_chunk', text: 'reply.' }), event_id: 'boot-2' }
        mocked.openTaskRunStream
            .mockResolvedValueOnce(firstStream.response)
            .mockResolvedValueOnce(secondStream.response)
        mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))
        const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
        try {
            await act(async () => {})
            await act(async () => {
                firstStream.push(first, 'log-0')
                if (published) firstStream.push({}, undefined, 'keepalive')
                firstStream.push({ type: 'resync' }, undefined, 'end')
            })
            await waitFor(() => expect(mocked.openTaskRunStream).toHaveBeenCalledTimes(2))
            expect(mocked.openTaskRunStream.mock.calls[1]?.[2]?.lastEventId).toBeUndefined()
            await act(async () => {
                secondStream.push(first, 'log-0')
                secondStream.push(last, 'log-1')
                secondStream.push({}, undefined, 'keepalive')
            })
            expect(result.current.items).toEqual([expect.objectContaining({ kind: 'assistant', text: 'Saved reply.' })])
        } finally {
            unmount()
        }
    })

    test.each(['project', 'session'])(
        'a %s switch drops the old session and rejects captured callbacks',
        async (changed) => {
            const previous = useAuthStore.getState().projectId
            useAuthStore.setState({ projectId: 1 })
            mocked.getTask.mockResolvedValue(task(run({ status: 'completed' })))
            mocked.getTaskRunLogs.mockResolvedValue([logLine({ sessionUpdate: 'agent_message', text: 'Project one' })])
            const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
            try {
                await waitFor(() => expect(result.current.history.status).toBe('idle'))
                expect(result.current.items).toHaveLength(1)
                const send = result.current.send
                await act(async () => {
                    if (changed === 'session') setSessionTokens(getSessionTokens())
                    useAuthStore.setState({ projectId: changed === 'project' ? 2 : 1 })
                })
                expect(result.current.taskId).toBeNull()
                expect(result.current.items).toEqual([])
                await expect(send('Continue', { kind: 'none' })).resolves.toBe(false)
                expect(mocked.startTaskRun).not.toHaveBeenCalled()
                expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
                expect(mocked.getTask).toHaveBeenCalledTimes(1)
            } finally {
                unmount()
                useAuthStore.setState({ projectId: previous })
            }
        }
    )

    test('a task create completing after a project switch cannot start or delete in the new project', async () => {
        const previous = useAuthStore.getState().projectId
        useAuthStore.setState({ projectId: 1 })
        let finishCreate!: (created: TaskCreateResponseApi) => void
        mocked.createTask.mockReturnValue(
            new Promise((resolve) => {
                finishCreate = resolve
            })
        )
        const { result, unmount } = renderHook(() => useSession({}))
        try {
            let sending!: Promise<boolean>
            act(() => {
                sending = result.current.send('Old project', { kind: 'none' })
            })
            await act(async () => {
                useAuthStore.setState({ projectId: 2 })
            })
            await act(async () => {
                finishCreate({ ...task(run({})), latest_run: null })
                await sending
            })
            expect(mocked.startTaskRun).not.toHaveBeenCalled()
            expect(mocked.deleteTask).not.toHaveBeenCalled()
            expect(result.current.taskId).toBeNull()
        } finally {
            unmount()
            useAuthStore.setState({ projectId: previous })
        }
    })

    test('keeps buffered history and its cursor when the stream rotates during catch-up', async () => {
        const firstStream = liveStream(false)
        const secondStream = liveStream(false)
        const first = {
            ...logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'Saved ' } }),
            event_id: 'first',
        }
        const last = {
            ...logLine({ sessionUpdate: 'agent_message_chunk', content: { text: 'reply.' } }),
            event_id: 'last',
        }
        mocked.openTaskRunStream
            .mockResolvedValueOnce(firstStream.response)
            .mockResolvedValueOnce(secondStream.response)
        mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))
        mocked.getTaskRun.mockResolvedValue(run({ status: 'in_progress' }))
        const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
        try {
            await act(async () => {})
            await act(async () => {
                firstStream.push(first, 'log-0')
                firstStream.push({ type: 'rotated' }, undefined, 'end')
            })
            await waitFor(() => expect(mocked.openTaskRunStream).toHaveBeenCalledTimes(2))
            expect(mocked.openTaskRunStream.mock.calls[1]?.[2]?.lastEventId).toBe('log-0')
            expect(result.current.items).toEqual([])
            await act(async () => {
                secondStream.push(last, 'log-1')
                secondStream.push({}, undefined, 'keepalive')
            })
            expect(result.current.items).toEqual([expect.objectContaining({ kind: 'assistant', text: 'Saved reply.' })])
        } finally {
            unmount()
        }
    })

    test('treats a new connection backlog as replay after the first hydration', async () => {
        const firstStream = liveStream()
        const secondStream = liveStream(false)
        mocked.openTaskRunStream
            .mockResolvedValueOnce(firstStream.response)
            .mockResolvedValueOnce(secondStream.response)
        mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))
        mocked.getTaskRun.mockResolvedValue(run({ status: 'in_progress' }))
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: {} })
        const { result, unmount } = renderHook(() => useSession({ taskId: TASK_ID }))
        try {
            await waitFor(() => expect(result.current.history.status).toBe('idle'))
            await act(async () => {
                firstStream.push({ type: 'rotated' }, undefined, 'end')
            })
            await waitFor(() => expect(mocked.openTaskRunStream).toHaveBeenCalledTimes(2))
            await act(async () => {
                secondStream.push(
                    {
                        type: 'notification',
                        notification: {
                            method: '_posthog/permission_request',
                            params: {
                                type: 'permission_request',
                                requestId: 'old-request',
                                options: [
                                    { optionId: 'allow', kind: 'allow_once', name: 'Yes' },
                                    { optionId: 'reject', kind: 'reject_once', name: 'No' },
                                ],
                                toolCall: {
                                    toolCallId: 'old-tool',
                                    title: 'Run tests',
                                    kind: 'execute',
                                    _meta: { claudeCode: { toolName: 'Bash' } },
                                },
                            },
                        },
                    },
                    '101-0'
                )
            })
            expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
            await act(async () => {
                secondStream.push({}, undefined, 'keepalive')
            })
            expect(result.current.decision?.question.id).toBe('old-request')
            expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
        } finally {
            unmount()
        }
    })

    test.each<[string, TaskRunApi, ChatRunOptions, Record<string, unknown>]>([
        [
            'the picked model',
            run({ status: 'completed', model: 'claude-sonnet-5', runtime_adapter: 'claude' }),
            OPUS_PLAN,
            {
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'plan',
            },
        ],
        [
            'an untouched model, keeping the ended run on its harness with the mode mapped onto it',
            run({ status: 'completed', model: 'gpt-5.5', runtime_adapter: 'codex' }),
            { model: 'default', permissionMode: 'acceptEdits' },
            { initial_permission_mode: 'auto' },
        ],
    ])(
        'a message to an ended run starts a resume run with %s instead of a command',
        async (_label, ended, options, fields) => {
            mocked.getTask.mockResolvedValue(task(ended))
            mocked.getTaskRunLogs.mockResolvedValue([
                logLine({ sessionUpdate: 'user_message_chunk', content: { text: 'Fix the flaky checkout test' } }),
                logLine({ sessionUpdate: 'agent_message', content: { text: 'Done. The PR is open.' } }),
            ])
            const successor = run({ id: 'run-2', status: 'queued' })
            mocked.startTaskRun.mockResolvedValue({ ...task(successor), run: successor })

            const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
            await waitFor(() => expect(result.current?.history.status).toBe('idle'))
            expect(result.current?.items.map((item) => item.kind)).toEqual(['user', 'assistant'])

            await act(async () => {
                await result.current?.send('Rename the helper too', { kind: 'none' }, options)
            })

            expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
            expect(mocked.startTaskRun).toHaveBeenCalledWith(
                TASK_ID,
                {
                    mode: 'interactive',
                    pending_user_message: 'Rename the helper too',
                    resume_from_run_id: 'run-1',
                    ...fields,
                },
                expect.anything()
            )
            expect(result.current?.runId).toBe('run-2')
            expect(result.current?.items.at(-1)).toMatchObject({ kind: 'user', text: 'Rename the helper too' })
            expect(mocked.openTaskRunStream).toHaveBeenCalledWith(TASK_ID, 'run-2', expect.anything())
        }
    )

    const OPUS_PLAN_FIELDS = {
        runtime_adapter: 'claude',
        model: 'claude-opus-5-5',
        reasoning_effort: 'high',
        initial_permission_mode: 'plan',
    }

    test.each<[string, ChatContext, ChatRunOptions, Record<string, unknown>, Record<string, unknown>]>([
        [
            'a plain question creates a PostHog AI chat named from the question',
            { kind: 'none' },
            OPUS_PLAN,
            {
                title: '',
                description: 'Why did signups drop?',
                origin_product: 'posthog_ai',
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'plan',
                pending_user_message: 'Why did signups drop?',
            },
            OPUS_PLAN_FIELDS,
        ],
        [
            'an untouched model sends only the mode, so the server applies the stored default',
            { kind: 'none' },
            DEFAULT_PLAN,
            {
                title: '',
                description: 'Why did signups drop?',
                origin_product: 'posthog_ai',
                initial_permission_mode: 'plan',
                pending_user_message: 'Why did signups drop?',
            },
            { initial_permission_mode: 'plan' },
        ],
        [
            'one attached report creates an Inbox discussion task',
            REPORT_CONTEXT,
            OPUS_PLAN,
            {
                title: 'Checkout errors spike',
                description: chatPrompt('Why did signups drop?', REPORT_CONTEXT),
                origin_product: 'signal_report',
                signal_report: 'rep-1',
                signal_report_task_relationship: 'discussion',
                signal_report_discussion_question: 'Why did signups drop?',
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                pending_user_message: chatPrompt('Why did signups drop?', REPORT_CONTEXT),
            },
            { run_source: 'signal_report', signal_report_id: 'rep-1', ...OPUS_PLAN_FIELDS },
        ],
    ])('%s, then starts its interactive run', async (_label, context, options, createBody, runFields) => {
        const created = { ...task(run({})), title: 'Signups drop', latest_run: null }
        mocked.createTask.mockResolvedValue(created)
        const first = run({ status: 'queued' })
        mocked.startTaskRun.mockResolvedValue({ ...created, run: first })

        const { result } = renderHook(() => useSession({}))
        expect(result.current.taskId).toBeNull()
        await act(async () => {
            await result.current.start('Why did signups drop?', context, options)
        })

        expect(mocked.createTask).toHaveBeenCalledWith(createBody, expect.anything())
        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            {
                mode: 'interactive',
                pending_user_message: chatPrompt('Why did signups drop?', context),
                ...runFields,
            },
            expect.anything()
        )
        expect(result.current.taskId).toBe(TASK_ID)
        expect(result.current.title).toBe('Signups drop')
        expect(result.current.items).toMatchObject([{ kind: 'user', text: 'Why did signups drop?' }])
        expect(mocked.openTaskRunStream).toHaveBeenCalledWith(TASK_ID, 'run-1', expect.anything())
    })

    test('a refused first run deletes the new task and hands back the message', async () => {
        mocked.createTask.mockResolvedValue({ ...task(run({})), latest_run: null })
        mocked.startTaskRun.mockRejectedValue(
            new ApiError(403, {
                code: 'code_access_required',
                error: 'PostHog Desktop access is required to run tasks in the cloud.',
            })
        )

        const { result } = renderHook(() => useSession({}))
        await act(async () => {
            await result.current.start('Why did signups drop?', { kind: 'none' }, OPUS_PLAN)
        })

        expect(mocked.deleteTask).toHaveBeenCalledWith(TASK_ID)
        expect(result.current.taskId).toBeNull()
        expect(result.current.items).toEqual([])
        expect(result.current.notice).toBe('PostHog Desktop access is required to run tasks in the cloud.')
        expect(result.current.unsentText).toBe('Why did signups drop?')
    })

    test.each([false, true])('a closed composer reports whether creation accepted a run: %s', async (accepted) => {
        let finishCreate: (created: TaskCreateResponseApi) => void = () => undefined
        mocked.createTask.mockReturnValue(
            new Promise<TaskCreateResponseApi>((resolve) => {
                finishCreate = resolve
            })
        )

        const { result, unmount } = renderHook(() => useSession({}))
        let sending: Promise<boolean> = Promise.resolve(false)
        act(() => {
            sending = result.current.start('Why did signups drop?', { kind: 'none' }, OPUS_PLAN)
        })
        await waitFor(() => expect(mocked.createTask).toHaveBeenCalled())
        unmount()
        finishCreate({ ...task(run({})), latest_run: accepted ? run({}) : null })
        expect(await sending).toBe(accepted)

        if (accepted) {
            expect(mocked.deleteTask).not.toHaveBeenCalled()
        } else {
            expect(mocked.deleteTask).toHaveBeenCalledWith(TASK_ID)
        }
        expect(mocked.startTaskRun).not.toHaveBeenCalled()
    })

    test('a run accepted after its composer closes reports a successful send', async () => {
        mocked.createTask.mockResolvedValue({ ...task(run({})), latest_run: null })
        let finishRun: (response: Awaited<ReturnType<typeof tasks.startTaskRun>>) => void = () => undefined
        mocked.startTaskRun.mockReturnValue(
            new Promise((resolve) => {
                finishRun = resolve
            })
        )
        const { result, unmount } = renderHook(() => useSession({}))
        let sending = Promise.resolve(false)
        act(() => {
            sending = result.current.start('Summarize this report', { kind: 'none' }, OPUS_PLAN)
        })
        await waitFor(() => expect(mocked.startTaskRun).toHaveBeenCalled())
        unmount()
        finishRun({ ...task(run({ status: 'in_progress' })), run: run({ status: 'in_progress' }) })
        expect(await sending).toBe(true)
        expect(mocked.deleteTask).not.toHaveBeenCalled()
        expect(mocked.openTaskRunStream).not.toHaveBeenCalled()
    })

    test('after a first run fails with a 5xx, the next message goes to the run the server did start', async () => {
        mocked.createTask.mockResolvedValue({ ...task(run({})), latest_run: null })
        mocked.startTaskRun.mockRejectedValue(new ApiError(500, undefined))

        const { result } = renderHook(() => useSession({}))
        await act(async () => {
            await result.current.start('Why did signups drop?', { kind: 'none' }, DEFAULT_AUTO)
        })
        expect(mocked.deleteTask).not.toHaveBeenCalled()
        expect(result.current.taskId).toBe(TASK_ID)
        expect(result.current.unsentText).toBe('Why did signups drop?')

        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', state: { initial_permission_mode: 'auto' } }))
        )
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: {} })
        await act(async () => {
            await result.current.send('Why did signups drop?', { kind: 'none' }, DEFAULT_AUTO)
        })

        expect(mocked.startTaskRun).toHaveBeenCalledTimes(1)
        expect(sentCommands()).toEqual([{ method: 'user_message', params: { content: 'Why did signups drop?' } }])
        expect(result.current.runId).toBe('run-1')
    })

    test('a new chat stages its files on the created task and starts the run with their ids', async () => {
        mocked.createTask.mockResolvedValue({ ...task(run({})), latest_run: null })
        mocked.startTaskRun.mockResolvedValue({ ...task(run({ status: 'queued' })), run: run({ status: 'queued' }) })
        upload.mockResolvedValueOnce(['art-1'])

        const { result } = renderHook(() => useSession({}))
        await act(async () => {
            await result.current.start('What is this?', { kind: 'none' }, DEFAULT_AUTO, { attachments: [SHOT] })
        })

        expect(upload).toHaveBeenCalledWith({ kind: 'staged', taskId: TASK_ID }, [SHOT], expect.any(AbortSignal))
        expect(mocked.createTask.mock.invocationCallOrder[0]).toBeLessThan(upload.mock.invocationCallOrder[0] ?? 0)
        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            expect.objectContaining({ pending_user_artifact_ids: ['art-1'] }),
            expect.anything()
        )
        expect(mocked.createTask.mock.calls[0]?.[0]).not.toHaveProperty('pending_user_artifact_ids')
    })

    test('a follow-up uploads to the live run, and stages the files again when that run has ended', async () => {
        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', state: { initial_permission_mode: 'auto' } }))
        )
        mocked.sendTaskRunCommand.mockRejectedValueOnce(new ApiError(409, { error: 'Task run workflow has ended' }))
        mocked.startTaskRun.mockResolvedValue({
            ...task(run({ id: 'run-2', status: 'queued' })),
            run: run({ id: 'run-2' }),
        })
        upload.mockResolvedValueOnce(['run-art']).mockResolvedValueOnce(['staged-art'])

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current.runStatus).toBe('in_progress'))
        let sent = false
        await act(async () => {
            sent = await result.current.send('What is this?', { kind: 'none' }, DEFAULT_AUTO, { attachments: [SHOT] })
        })

        expect(sent).toBe(true)
        expect(upload.mock.calls.map(([target]) => target)).toEqual([
            { kind: 'run', taskId: TASK_ID, runId: 'run-1' },
            { kind: 'staged', taskId: TASK_ID },
        ])
        expect(sentCommands()).toEqual([
            { method: 'user_message', params: { content: 'What is this?', artifact_ids: ['run-art'] } },
        ])
        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            expect.objectContaining({ resume_from_run_id: 'run-1', pending_user_artifact_ids: ['staged-art'] }),
            expect.anything()
        )
    })

    test.each<[string, Error, number]>([
        ['an S3 post', new AttachmentUploadError("Couldn't upload shot.png", 403), 403],
        ['prepare', new ApiError(400, { error: 'Artifact upload not found in object storage' }), 400],
    ])(
        'a failed upload in %s sends nothing, takes the bubble back and deletes the empty task',
        async (_step, failure, status) => {
            const capture = jest.fn()
            setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
            mocked.createTask.mockResolvedValue({ ...task(run({})), latest_run: null })
            upload.mockRejectedValueOnce(failure)

            const { result } = renderHook(() => useSession({}))
            let sent = true
            await act(async () => {
                sent = await result.current.start('What is this?', { kind: 'none' }, DEFAULT_AUTO, {
                    attachments: [SHOT],
                })
            })
            setAnalyticsClient(null)

            expect(sent).toBe(false)
            expect(mocked.startTaskRun).not.toHaveBeenCalled()
            expect(mocked.deleteTask).toHaveBeenCalledWith(TASK_ID)
            expect(result.current.items).toEqual([])
            expect(result.current.unsentText).toBe('What is this?')
            expect(result.current.notice).toBe("Your files didn't upload. Try again.")
            expect(capture).toHaveBeenCalledWith('mobile_chat_file_upload_failed', { status, new_task: true })
            expect(capture).toHaveBeenCalledWith('mobile_session_send_failed', {
                code: 'upload_failed',
                new_task: true,
            })
        }
    )

    test('a fresh run of an opened Inbox discussion task keeps its report as the run source', async () => {
        mocked.getTask.mockResolvedValue({ ...task(run({})), signal_report: 'rep-1', latest_run: null })
        const first = run({ status: 'queued' })
        mocked.startTaskRun.mockResolvedValue({ ...task(first), run: first })

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current.history.status).toBe('idle'))
        await act(async () => {
            await result.current.send('Is this still happening?', { kind: 'none' }, DEFAULT_AUTO)
        })

        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            {
                mode: 'interactive',
                pending_user_message: 'Is this still happening?',
                run_source: 'signal_report',
                signal_report_id: 'rep-1',
                initial_permission_mode: 'auto',
            },
            expect.anything()
        )
    })

    test('a mode the agent reports after the app set one wins, so the next message sets the mode again', async () => {
        const stream = liveStream()
        mocked.openTaskRunStream.mockResolvedValueOnce(stream.response)
        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', runtime_adapter: 'claude', state: { initial_permission_mode: 'auto' } }))
        )
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: {} })

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current.runStatus).toBe('in_progress'))
        await act(async () => {
            await result.current.send('Plan the fix', { kind: 'none' }, DEFAULT_PLAN)
        })
        expect(result.current.runConfig?.permissionMode).toBe('plan')

        // Approving the plan with the auto option moves the agent out of Plan.
        act(() => {
            stream.push(logLine({ sessionUpdate: 'current_mode_update', currentModeId: 'auto' }))
        })
        await waitFor(() => expect(result.current.runConfig?.permissionMode).toBe('auto'))
        await act(async () => {
            await result.current.send('Plan the next one', { kind: 'none' }, DEFAULT_PLAN)
        })

        expect(sentCommands()).toEqual([
            { method: 'set_config_option', params: { configId: 'mode', value: 'plan' } },
            { method: 'user_message', params: { content: 'Plan the fix' } },
            { method: 'set_config_option', params: { configId: 'mode', value: 'plan' } },
            { method: 'user_message', params: { content: 'Plan the next one' } },
        ])
    })

    test('a message to a live run first sets only the options that changed', async () => {
        mocked.getTask.mockResolvedValue(
            task(
                run({
                    status: 'in_progress',
                    runtime_adapter: 'claude',
                    model: 'claude-sonnet-5-5',
                    reasoning_effort: 'high',
                    state: { initial_permission_mode: 'auto' },
                })
            )
        )
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: {} })

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current.runStatus).toBe('in_progress'))
        await act(async () => {
            await result.current.send('Now plan the fix', { kind: 'none' }, OPUS_PLAN)
        })
        await act(async () => {
            await result.current.send('Go on', { kind: 'none' }, OPUS_PLAN)
        })

        expect(sentCommands()).toEqual([
            { method: 'set_config_option', params: { configId: 'model', value: 'claude-opus-5-5' } },
            { method: 'set_config_option', params: { configId: 'mode', value: 'plan' } },
            { method: 'user_message', params: { content: 'Now plan the fix' } },
            { method: 'user_message', params: { content: 'Go on' } },
        ])
    })

    test('historical tools and mode updates stay idle, and stop is available only after live generation', async () => {
        const stream = liveStream()
        mocked.openTaskRunStream.mockResolvedValueOnce(stream.response)
        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', runtime_adapter: 'claude', state: { initial_permission_mode: 'plan' } }))
        )
        mocked.getTaskRunLogs.mockResolvedValue([
            logLine({
                sessionUpdate: 'tool_call',
                toolCallId: 'old-tool',
                title: 'Read source file',
                status: 'completed',
            }),
        ])
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: {} })

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current?.runStatus).toBe('in_progress'))
        expect(result.current.phase).toBe('idle')
        act(() => {
            stream.push(logLine({ sessionUpdate: 'current_mode_update', currentModeId: 'auto' }))
        })
        await waitFor(() => expect(result.current.runConfig?.permissionMode).toBe('auto'))
        expect(result.current.phase).toBe('idle')
        act(() => {
            result.current?.stop()
        })

        expect(result.current?.notice).toBe("The agent hasn't started yet.")
        expect(result.current?.isStopping).toBe(false)
        expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
        act(() => {
            stream.push(LIVE_TOOL_CALL)
        })
        await waitFor(() => expect(result.current.phase).toBe('working'))
        act(() => {
            result.current.stop()
        })
        expect(sentCommands()).toEqual([{ method: 'cancel' }])
        act(() => {
            stream.push({ type: 'notification', notification: { method: '_posthog/turn_complete', params: {} } })
        })
        await waitFor(() => expect(result.current.isStopping).toBe(false))
    })

    test('a steer joins the live turn only once the stream shows the agent generating', async () => {
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const stream = liveStream(false)
        stream.push(LIVE_TOOL_CALL, 'log-0')
        stream.push({}, undefined, 'keepalive')
        mocked.openTaskRunStream.mockResolvedValueOnce(stream.response)
        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', runtime_adapter: 'claude', state: { initial_permission_mode: 'auto' } }))
        )
        mocked.sendTaskRunCommand.mockResolvedValue({ jsonrpc: '2.0', result: { queued: true } })
        try {
            const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
            await waitFor(() => expect(result.current.history.status).toBe('idle'))
            expect(result.current.canSteer).toBe(false)
            await act(async () => {
                await result.current.send('Check the logs', { kind: 'none' }, DEFAULT_AUTO, {
                    steer: true,
                    queuedCount: 1,
                })
            })

            act(() => {
                stream.push(LIVE_TOOL_CALL)
            })
            await waitFor(() => expect(result.current.canSteer).toBe(true))
            await act(async () => {
                await result.current.send('Also cover refunds', { kind: 'none' }, DEFAULT_AUTO, {
                    steer: true,
                    queuedCount: 2,
                })
            })

            expect(sentCommands()).toEqual([
                { method: 'user_message', params: { content: 'Check the logs' } },
                { method: 'user_message', params: { content: 'Also cover refunds', steer: true } },
            ])
            const sent = capture.mock.calls.filter(([event]) => event === 'mobile_session_sent')
            expect(sent.map(([, properties]) => properties)).toEqual([
                expect.objectContaining({ delivery: 'queue', queued_count: 1 }),
                expect.objectContaining({ delivery: 'steer', queued_count: 2 }),
            ])
        } finally {
            setAnalyticsClient(null)
        }
    })

    test('a steer to a run that ended resumes it as an ordinary follow-up', async () => {
        const stream = liveStream()
        mocked.openTaskRunStream.mockResolvedValueOnce(stream.response)
        mocked.getTask.mockResolvedValue(
            task(run({ status: 'in_progress', runtime_adapter: 'claude', state: { initial_permission_mode: 'auto' } }))
        )
        mocked.sendTaskRunCommand.mockRejectedValue(new ApiError(409, { code: 'run_ended' }))
        const successor = run({ id: 'run-2', status: 'queued' })
        mocked.startTaskRun.mockResolvedValue({ ...task(successor), run: successor })

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current.history.status).toBe('idle'))
        act(() => {
            stream.push(LIVE_TOOL_CALL)
        })
        await waitFor(() => expect(result.current.canSteer).toBe(true))
        await act(async () => {
            await result.current.send('Also cover refunds', { kind: 'none' }, DEFAULT_AUTO, { steer: true })
        })

        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            expect.objectContaining({ pending_user_message: 'Also cover refunds', resume_from_run_id: 'run-1' }),
            expect.anything()
        )
        expect(result.current.runId).toBe('run-2')
        expect(result.current.notice).toBeUndefined()
        expect(result.current.items.filter((item) => item.kind === 'user')).toEqual([
            expect.objectContaining({ text: 'Also cover refunds' }),
        ])
    })
})
