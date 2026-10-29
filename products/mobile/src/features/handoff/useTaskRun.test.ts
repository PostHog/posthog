import { ApiError } from '@/api/client'
import { getTask, getTaskRun, openTaskRunStream, type TaskRunApi } from '@/api/tasks'

import { deliverPermissionResponse } from './commands'
import { useHandoffStore } from './handoffStore'
import { visibleAnswer } from './liveReport'
import { HYDRATION_QUIET_MS } from './runHydration'
import { followRun } from './useTaskRun'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('./commands', () => ({ deliverPermissionResponse: jest.fn() }))
jest.mock('@/api/tasks', () => ({
    getTask: jest.fn(),
    getTaskRun: jest.fn(),
    openTaskRunStream: jest.fn(),
}))

const TASK = 'task-lifecycle'
const REPORT = 'report-lifecycle'
const RUN: TaskRunApi = {
    id: 'run-lifecycle',
    task: TASK,
    status: 'in_progress',
    stage: null,
    branch: null,
    error_message: null,
    output: null,
    completed_at: null,
}

function endedStream(): Response {
    let sent = false
    return {
        body: {
            getReader: () => ({
                read: async () => {
                    if (sent) {
                        return { done: true }
                    }
                    sent = true
                    return { value: new TextEncoder().encode('event: stream-end\ndata: {}\n\n'), done: false }
                },
                cancel: async () => undefined,
            }),
        },
    } as unknown as Response
}

function controlledStream(): { response: Response; send: (text: string) => void; fail: () => void; close: () => void } {
    type Read = { value?: Uint8Array; done: boolean }
    const queued: (Read | Error)[] = []
    let waiting: { resolve: (read: Read) => void; reject: (error: Error) => void } | undefined
    const deliver = (next: Read | Error): void => {
        if (waiting) {
            const target = waiting
            waiting = undefined
            if (next instanceof Error) {
                target.reject(next)
            } else {
                target.resolve(next)
            }
        } else {
            queued.push(next)
        }
    }
    return {
        response: {
            body: {
                getReader: () => ({
                    read: () =>
                        new Promise<Read>((resolve, reject) => {
                            const next = queued.shift()
                            if (next instanceof Error) {
                                reject(next)
                            } else if (next) {
                                resolve(next)
                            } else {
                                waiting = { resolve, reject }
                            }
                        }),
                    cancel: async () => {
                        deliver({ done: true })
                    },
                }),
            },
        } as unknown as Response,
        send: (text) => deliver({ value: new TextEncoder().encode(text), done: false }),
        fail: () => deliver(new Error('connection dropped')),
        close: () => deliver({ done: true }),
    }
}

function event(id: string, data: unknown): string {
    return `id: ${id}\ndata: ${JSON.stringify(data)}\n\n`
}

function toolFrame(title: string, eventId: string): unknown {
    return {
        event_id: eventId,
        type: 'notification',
        notification: {
            method: 'session/update',
            params: { update: { sessionUpdate: 'tool_call', toolCallId: eventId, title } },
        },
    }
}

function turnEnd(eventId: string): unknown {
    return { event_id: eventId, type: 'notification', notification: { method: '_posthog/turn_complete', params: {} } }
}

const HISTORICAL_PERMISSION = {
    event_id: 'permission-history',
    type: 'permission_request',
    requestId: 'history-request',
    options: [{ optionId: 'allow', kind: 'allow_once', name: 'Yes' }],
    toolCall: {
        toolCallId: 'permission-tool',
        title: 'Run tests',
        kind: 'execute',
        _meta: { claudeCode: { toolName: 'Bash' } },
    },
}

describe('report run connection lifecycle', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.clearAllMocks()
        useHandoffStore.setState({ reports: {} })
        jest.mocked(getTask).mockResolvedValue({ id: TASK, title: '', signal_report: REPORT, latest_run: RUN })
        jest.mocked(getTaskRun).mockResolvedValue(RUN)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test('shows reconnecting while admission retries, then unavailable when access is refused', async () => {
        jest.mocked(openTaskRunStream)
            .mockRejectedValueOnce(new Error('offline'))
            .mockRejectedValueOnce(new ApiError(403, {}))
        const followed = followRun({
            reportId: REPORT,
            taskId: TASK,
            runId: RUN.id,
            signal: new AbortController().signal,
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBe('reconnecting')
        await jest.advanceTimersByTimeAsync(2000)
        await followed
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBe('unavailable')
    })

    test('uses a newly resumed latest run and settles completed runs without a disconnect warning', async () => {
        const resumed = { ...RUN, id: 'run-resumed', status: 'completed' as const }
        jest.mocked(getTask).mockResolvedValue({ id: TASK, title: '', signal_report: REPORT, latest_run: resumed })
        const snapshots: string[] = []
        await followRun({
            reportId: REPORT,
            taskId: TASK,
            runId: RUN.id,
            signal: new AbortController().signal,
            onTaskSnapshot: (task) => snapshots.push(task.latest_run?.id ?? ''),
        })
        expect(snapshots).toEqual(['run-resumed'])
        expect(useHandoffStore.getState().reports[REPORT]?.live).toMatchObject({
            runId: 'run-resumed',
            status: 'completed',
        })
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBeUndefined()
        expect(openTaskRunStream).not.toHaveBeenCalled()
    })

    test('a late canceled bootstrap cannot replace the task now being followed', async () => {
        let finish!: (task: Awaited<ReturnType<typeof getTask>>) => void
        jest.mocked(getTask).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finish = resolve
                })
        )
        const controller = new AbortController()
        const cacheSnapshot = jest.fn()
        const followed = followRun({
            reportId: REPORT,
            taskId: TASK,
            runId: RUN.id,
            signal: controller.signal,
            onTaskSnapshot: cacheSnapshot,
        })
        controller.abort()
        useHandoffStore.getState().setAnswer(REPORT, {
            questionId: 'old-question',
            question: { id: 'old-question', question: 'Continue?', options: [] },
            text: 'Yes',
            delivery: 'delivered',
            activity: 0,
        })
        useHandoffStore.getState().setPartial(REPORT, { requestId: 'old-question', labels: ['Yes'] })
        useHandoffStore.getState().setNotice(REPORT, 'Old notice')
        const newer = { ...RUN, id: 'run-next', task: 'task-next' }
        useHandoffStore.getState().applySnapshot(REPORT, newer.task, newer)
        finish({ id: TASK, title: '', signal_report: REPORT, latest_run: RUN })
        await followed
        expect(useHandoffStore.getState().reports[REPORT]?.live?.runId).toBe('run-next')
        expect(useHandoffStore.getState().reports[REPORT]).toMatchObject({
            answer: undefined,
            partial: undefined,
            notice: undefined,
        })
        expect(cacheSnapshot).not.toHaveBeenCalled()
        expect(openTaskRunStream).not.toHaveBeenCalled()
    })

    test('a nonterminal stream end stops claiming execution and refreshes the task snapshot', async () => {
        jest.mocked(openTaskRunStream).mockResolvedValue(endedStream())
        const refresh = jest.fn()
        await followRun({
            reportId: REPORT,
            taskId: TASK,
            runId: RUN.id,
            signal: new AbortController().signal,
            onRefresh: refresh,
        })
        expect(useHandoffStore.getState().reports[REPORT]?.live).toMatchObject({ phase: 'unknown' })
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBeUndefined()
        expect(refresh).toHaveBeenCalledTimes(1)
    })

    test('slow durable history stays private, settles once, and new live activity updates immediately', async () => {
        const stream = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValue(stream.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        const publications: string[] = []
        const unsubscribe = useHandoffStore.subscribe((state) => {
            const live = state.reports[REPORT]?.live
            if (live) {
                publications.push(`${live.phase}:${live.toolTitle ?? ''}:${live.pending?.record.requestId ?? ''}`)
            }
        })
        try {
            for (const [index, frame] of [
                toolFrame('Read old.ts', 'old-tool'),
                HISTORICAL_PERMISSION,
                turnEnd('old-complete'),
            ].entries()) {
                stream.send(event(`log-${index}`, frame))
                await jest.advanceTimersByTimeAsync(HYDRATION_QUIET_MS * 2)
                expect(publications).toEqual([])
            }
            stream.send(event('1900000000000-0', { type: 'task_run_state', run_id: RUN.id, status: 'in_progress' }))
            await jest.advanceTimersByTimeAsync(HYDRATION_QUIET_MS)
            expect(publications).toEqual(['idle::'])
            expect(deliverPermissionResponse).not.toHaveBeenCalled()
            stream.send(event('1900000000001-0', toolFrame('Edit new.ts', 'new-tool')))
            await jest.advanceTimersByTimeAsync(0)
            expect(publications.at(-1)).toBe('working:Editing new.ts:')
        } finally {
            unsubscribe()
            controller.abort()
            await followed
        }
    })

    test('rotation keeps private state and cursor together, and abort discards unpublished replay on reopen', async () => {
        const first = controlledStream()
        const rotated = controlledStream()
        const reopened = controlledStream()
        jest.mocked(openTaskRunStream)
            .mockResolvedValueOnce(first.response)
            .mockResolvedValueOnce(rotated.response)
            .mockResolvedValueOnce(reopened.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        first.send(event('log-0', HISTORICAL_PERMISSION))
        await jest.advanceTimersByTimeAsync(HYDRATION_QUIET_MS * 2)
        first.send('event: end\ndata: {"type":"rotated"}\n\n')
        await jest.advanceTimersByTimeAsync(0)
        expect(openTaskRunStream).toHaveBeenLastCalledWith(
            TASK,
            RUN.id,
            expect.objectContaining({ lastEventId: 'log-0' })
        )
        expect(useHandoffStore.getState().reports[REPORT]?.live?.pending).toBeUndefined()
        controller.abort()
        await followed
        const nextController = new AbortController()
        const next = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: nextController.signal })
        await jest.advanceTimersByTimeAsync(0)
        expect(openTaskRunStream).toHaveBeenLastCalledWith(
            TASK,
            RUN.id,
            expect.objectContaining({ lastEventId: undefined })
        )
        reopened.send(event('log-0', HISTORICAL_PERMISSION))
        reopened.send('event: keepalive\ndata: {}\n\n')
        await jest.advanceTimersByTimeAsync(0)
        expect(useHandoffStore.getState().reports[REPORT]?.live?.pending?.record.requestId).toBe('history-request')
        expect(deliverPermissionResponse).not.toHaveBeenCalled()
        nextController.abort()
        await next
    })

    test('an answer sent during catchup stays delivered and its handled request cannot return', async () => {
        useHandoffStore.getState().applySnapshot(REPORT, TASK, RUN)
        const stream = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValue(stream.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        stream.send(event('log-0', HISTORICAL_PERMISSION))
        await jest.advanceTimersByTimeAsync(0)
        useHandoffStore.getState().markHandled(REPORT, 'history-request')
        useHandoffStore.getState().setAnswer(REPORT, {
            questionId: 'history-request',
            question: { id: 'history-request', question: 'Run tests?', options: [] },
            text: 'Yes',
            delivery: 'delivered',
            activity: 0,
        })
        stream.send('event: keepalive\ndata: {}\n\n')
        await jest.advanceTimersByTimeAsync(0)
        const entry = useHandoffStore.getState().reports[REPORT]
        expect(entry?.live?.pending).toBeUndefined()
        expect(visibleAnswer(entry, undefined)?.text).toBe('Yes')
        controller.abort()
        await followed
    })

    test('reconnect catches missed activity and uses the fresh snapshot without retaining an old answer', async () => {
        const first = controlledStream()
        const next = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValueOnce(first.response).mockResolvedValueOnce(next.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        first.send(event('1900000000010-0', turnEnd('prior-turn')))
        await jest.advanceTimersByTimeAsync(HYDRATION_QUIET_MS)
        const activity = useHandoffStore.getState().reports[REPORT]?.live?.activity ?? 0
        useHandoffStore.getState().setAnswer(REPORT, {
            questionId: 'old-answer',
            question: { id: 'old-answer', question: 'Continue?', options: [] },
            text: 'Yes',
            delivery: 'delivered',
            activity,
        })
        jest.mocked(getTaskRun).mockResolvedValue({
            ...RUN,
            stage: 'Fresh snapshot',
            output: { pr_url: 'https://github.com/example/repo/pull/12' },
        })
        first.fail()
        await jest.advanceTimersByTimeAsync(2000)
        next.send(event('1900000000011-0', toolFrame('Edit resumed.ts', 'resumed-tool')))
        next.send(event('1900000000012-0', turnEnd('resumed-turn')))
        await jest.advanceTimersByTimeAsync(HYDRATION_QUIET_MS)
        const entry = useHandoffStore.getState().reports[REPORT]
        expect(entry?.live).toMatchObject({
            phase: 'idle',
            turnEnded: true,
            prUrl: 'https://github.com/example/repo/pull/12',
        })
        expect(visibleAnswer(entry, undefined)).toBeUndefined()
        controller.abort()
        await followed
    })

    test('unmarked EOF keeps incomplete history private while reconnecting', async () => {
        const first = controlledStream()
        const second = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        first.send(event('log-0', HISTORICAL_PERMISSION))
        first.close()
        await jest.advanceTimersByTimeAsync(0)
        expect(useHandoffStore.getState().reports[REPORT]?.live?.pending).toBeUndefined()
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBe('reconnecting')
        await jest.advanceTimersByTimeAsync(2000)
        second.send(event('log-1', turnEnd('eof-complete')))
        second.send('event: keepalive\ndata: {}\n\n')
        await jest.advanceTimersByTimeAsync(0)
        expect(useHandoffStore.getState().reports[REPORT]?.live?.turnEnded).toBe(true)
        expect(useHandoffStore.getState().reports[REPORT]?.live?.pending).toBeUndefined()
        controller.abort()
        await followed
    })

    test('a terminal snapshot preserves every PR discovered in private history', async () => {
        const stream = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValue(stream.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        const first = 'https://github.com/example/repo/pull/1'
        const second = 'https://github.com/example/repo/pull/2'
        stream.send(event('log-0', { type: 'task_run_state', run_id: RUN.id, output: { pr_urls: [first, second] } }))
        jest.mocked(getTaskRun).mockResolvedValue({ ...RUN, status: 'completed', output: { pr_url: first } })
        stream.fail()
        await followed
        expect(useHandoffStore.getState().reports[REPORT]?.live).toMatchObject({
            status: 'completed',
            prUrls: [first, second],
        })
        expect(useHandoffStore.getState().reports[REPORT]?.live?.connection).toBeUndefined()
    })

    test('a replaced task stops the old follower before a final snapshot can overwrite its successor', async () => {
        const stream = controlledStream()
        jest.mocked(openTaskRunStream).mockResolvedValue(stream.response)
        const controller = new AbortController()
        const followed = followRun({ reportId: REPORT, taskId: TASK, runId: RUN.id, signal: controller.signal })
        await jest.advanceTimersByTimeAsync(0)
        const nextRun = { ...RUN, task: 'replacement-task', id: 'replacement-run' }
        useHandoffStore.getState().applySnapshot(REPORT, nextRun.task, nextRun)
        stream.send(event('1900000000020-0', toolFrame('Edit replaced.ts', 'replaced-tool')))
        await followed
        expect(useHandoffStore.getState().reports[REPORT]?.live).toMatchObject({
            taskId: nextRun.task,
            runId: nextRun.id,
        })
        expect(getTaskRun).not.toHaveBeenCalled()
    })
})
