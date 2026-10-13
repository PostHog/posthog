import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { TaskApi, TaskRunApi } from '@/api/tasks'
import * as tasks from '@/api/tasks'

import { useSession } from './useSession'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/api/tasks', () => ({
    ...jest.requireActual<typeof import('@/api/tasks')>('@/api/tasks'),
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

const mocked = jest.mocked(tasks)
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

function logLine(update: Record<string, unknown>): Record<string, unknown> {
    return { type: 'notification', notification: { method: 'session/update', params: { update } } }
}

describe('useSession', () => {
    afterEach(() => {
        jest.clearAllMocks()
    })

    test('a message to an ended run starts a resume run with the same model instead of a command', async () => {
        const ended = run({ status: 'completed', model: 'claude-sonnet-5', runtime_adapter: 'claude' })
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
            await result.current?.send('Rename the helper too', { kind: 'none' })
        })

        expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
        expect(mocked.startTaskRun).toHaveBeenCalledWith(
            TASK_ID,
            {
                mode: 'interactive',
                pending_user_message: 'Rename the helper too',
                resume_from_run_id: 'run-1',
                model: 'claude-sonnet-5',
                runtime_adapter: 'claude',
            },
            expect.anything()
        )
        expect(result.current?.runId).toBe('run-2')
        expect(result.current?.items.at(-1)).toMatchObject({ kind: 'user', text: 'Rename the helper too' })
        expect(mocked.openTaskRunStream).toHaveBeenCalledWith(TASK_ID, 'run-2', expect.anything())
    })

    test('stop before the agent generated anything asks to wait and sends no cancel', async () => {
        mocked.getTask.mockResolvedValue(task(run({ status: 'in_progress' })))

        const { result } = renderHook(() => useSession({ taskId: TASK_ID }))
        await waitFor(() => expect(result.current?.runStatus).toBe('in_progress'))
        act(() => {
            result.current?.stop()
        })

        expect(result.current?.notice).toBe("The agent hasn't started yet.")
        expect(result.current?.isStopping).toBe(false)
        expect(mocked.sendTaskRunCommand).not.toHaveBeenCalled()
    })
})
