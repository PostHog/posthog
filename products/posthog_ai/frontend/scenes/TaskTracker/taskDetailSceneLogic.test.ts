import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tasksLogic } from '../../logics/tasksLogic'
import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { taskDetailSceneLogic } from './taskDetailSceneLogic'

const createMockTask = (id: string): Task => ({
    id,
    task_number: 1,
    slug: `task-${id}`,
    title: `Task ${id}`,
    description: 'A test task',
    origin_product: OriginProduct.USER_CREATED,
    repository: 'test/repo',
    github_integration: null,
    signal_report: null,
    json_schema: null,
    internal: false,
    latest_run: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: null,
})

const createMockRun = (id: string, status: TaskRunStatus): TaskRun => ({
    id,
    task: 'task-123',
    stage: null,
    branch: null,
    status,
    environment: TaskRunEnvironment.CLOUD,
    log_url: null,
    error_message: null,
    output: null,
    state: {},
    artifacts: [],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    completed_at: null,
})

function createJsonResponse(payload: unknown): Response {
    return new Response(JSON.stringify(payload), {
        headers: { 'Content-Type': 'application/json' },
    })
}

function createFetchMock({
    runs = {},
    runsList = [],
}: {
    runs?: Record<string, TaskRun>
    runsList?: TaskRun[]
} = {}): typeof fetch {
    return jest.fn((input: RequestInfo | URL) => {
        const url = String(input)
        const taskRunMatch = url.match(/\/tasks\/([^/]+)\/runs\/([^/]+)\/$/)
        const runsListMatch = url.match(/\/tasks\/([^/]+)\/runs\/$/)
        const taskMatch = url.match(/\/tasks\/([^/]+)\/$/)

        if (taskRunMatch) {
            return Promise.resolve(
                createJsonResponse(runs[taskRunMatch[2]] ?? createMockRun(taskRunMatch[2], TaskRunStatus.COMPLETED))
            )
        }
        if (runsListMatch) {
            return Promise.resolve(createJsonResponse({ results: runsList }))
        }
        if (taskMatch) {
            return Promise.resolve(createJsonResponse(createMockTask(taskMatch[1])))
        }
        throw new Error(`Unexpected fetch url: ${url}`)
    }) as typeof fetch
}

describe('taskDetailSceneLogic', () => {
    const originalFetch = global.fetch

    beforeEach(() => {
        // featureFlagLogic persists flags to localStorage and hydrates as soon as initKeaTests
        // mounts the common logics, so clear before init or flags enabled in one test leak into
        // the next.
        window.localStorage.clear()
        // streamViaProxyEnabled is now purely flag-driven, so preflight no longer affects it. The
        // default test fixture has is_debug: true; pin it to false to keep the app context minimal
        // and unsurprising for these tests.
        window.POSTHOG_APP_CONTEXT = { preflight: { is_debug: false } } as unknown as typeof window.POSTHOG_APP_CONTEXT
        initKeaTests()
        global.fetch = createFetchMock()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        global.fetch = originalFetch
    })

    describe('setSelectedRunId cross-talk prevention', () => {
        it('only updates selectedRunId for the matching taskId', async () => {
            const logicA = taskDetailSceneLogic({ taskId: 'task-A' })
            const logicB = taskDetailSceneLogic({ taskId: 'task-B' })
            logicA.mount()
            logicB.mount()
            await expectLogic(logicA).toFinishAllListeners()
            await expectLogic(logicB).toFinishAllListeners()

            expect(logicA.values.selectedRunId).toBe(null)
            expect(logicB.values.selectedRunId).toBe(null)

            logicA.actions.setSelectedRunId('run-A', 'task-A')
            await expectLogic(logicA).toFinishAllListeners()
            await expectLogic(logicB).toFinishAllListeners()

            expect(logicA.values.selectedRunId).toBe('run-A')
            expect(logicB.values.selectedRunId).toBe(null)

            logicA.unmount()
            logicB.unmount()
        })

        it('runTaskSuccess only processes events for its own task', async () => {
            const logicA = taskDetailSceneLogic({ taskId: 'task-A' })
            const logicB = taskDetailSceneLogic({ taskId: 'task-B' })
            logicA.mount()
            logicB.mount()
            await expectLogic(logicA).toFinishAllListeners()
            await expectLogic(logicB).toFinishAllListeners()

            const taskAResult = {
                ...createMockTask('task-A'),
                latest_run: createMockRun('run-A', TaskRunStatus.QUEUED),
            }
            logicA.actions.runTaskSuccess(taskAResult)
            await expectLogic(logicA).toFinishAllListeners()
            await expectLogic(logicB).toFinishAllListeners()

            expect(logicA.values.selectedRunId).toBe('run-A')
            expect(logicB.values.selectedRunId).toBe(null)

            logicA.unmount()
            logicB.unmount()
        })
    })

    describe('updateRun', () => {
        it('updates run status in runs list when polling', async () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            const initialRun = createMockRun('run-456', TaskRunStatus.QUEUED)
            logic.actions.loadTaskRunsSuccess([initialRun])
            expect(logic.values.runs[0].status).toBe(TaskRunStatus.QUEUED)

            const updatedRun = createMockRun('run-456', TaskRunStatus.IN_PROGRESS)
            logic.actions.updateRun(updatedRun)

            expect(logic.values.runs[0].status).toBe(TaskRunStatus.IN_PROGRESS)
            logic.unmount()
        })

        it('does not affect other runs in the list', async () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            const run1 = createMockRun('run-1', TaskRunStatus.COMPLETED)
            const run2 = createMockRun('run-2', TaskRunStatus.QUEUED)
            logic.actions.loadTaskRunsSuccess([run1, run2])

            const updatedRun2 = createMockRun('run-2', TaskRunStatus.IN_PROGRESS)
            logic.actions.updateRun(updatedRun2)

            expect(logic.values.runs[0].status).toBe(TaskRunStatus.COMPLETED)
            expect(logic.values.runs[1].status).toBe(TaskRunStatus.IN_PROGRESS)
            logic.unmount()
        })

        it('inserts a run that was created before the refreshed list returns', async () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            const run = createMockRun('run-new', TaskRunStatus.QUEUED)
            logic.actions.updateRun(run)

            expect(logic.values.runs.map((existingRun) => existingRun.id)).toEqual(['run-new'])
            logic.unmount()
        })
    })

    describe('progressive selected run loading', () => {
        it('uses runs from the list without refetching selected run detail', async () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const fetchMock = global.fetch as jest.Mock
            fetchMock.mockClear()

            logic.actions.loadTaskRunsSuccess([createMockRun('run-in-list', TaskRunStatus.COMPLETED)])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.selectedRunId).toBe('run-in-list')
            expect(logic.values.selectedRun?.id).toBe('run-in-list')
            expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/runs/run-in-list/'))).toBe(false)
            logic.unmount()
        })

        it('fetches a deep-linked selected run that is not in the list', async () => {
            const runId = '00000000-0000-4000-8000-000000000456'
            global.fetch = createFetchMock({
                runs: { [runId]: createMockRun(runId, TaskRunStatus.COMPLETED) },
            })
            router.actions.push(`/tasks/task-123?runId=${runId}`)

            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.selectedRunId).toBe(runId)
            expect(logic.values.selectedRun?.id).toBe(runId)
            expect(
                (global.fetch as jest.Mock).mock.calls.some(([input]) => String(input).includes(`/runs/${runId}/`))
            ).toBe(true)

            logic.unmount()
        })
    })

    describe('loader failure state', () => {
        it('stores run-list failures for inline retry UI', () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.loadTaskRunsFailure('Could not load task runs', new ApiError('Could not load task runs', 500))

            expect(logic.values.runsError).toBe('Could not load task runs')
            logic.unmount()
        })

        it('stores selected-run not-found failures separately from retryable errors', () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.loadSelectedTaskRunFailure('Not found', new ApiError('Not found', 404))

            expect(logic.values.selectedRunNotFound).toBe(true)
            expect(logic.values.selectedRunError).toBe(null)
            logic.unmount()
        })

        it('stores selected-run non-404 failures for inline retry UI', () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.loadSelectedTaskRunFailure(
                'Could not load task run',
                new ApiError('Could not load task run', 500)
            )

            expect(logic.values.selectedRunNotFound).toBe(false)
            expect(logic.values.selectedRunError).toBe('Could not load task run')
            logic.unmount()
        })
    })

    describe('unified loading selectors', () => {
        it('reports the header + run log as pending while task and runs are still loading', () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()

            // afterMount fires loadTask + loadTaskRuns synchronously; nothing has resolved yet.
            expect(logic.values.isTaskPending).toBe(true)
            expect(logic.values.isRunPending).toBe(true)
            expect(logic.values.isHeaderLoading).toBe(true)
            logic.unmount()
        })

        it('clears pending once the task and its runs resolve', async () => {
            global.fetch = createFetchMock({ runsList: [createMockRun('run-1', TaskRunStatus.COMPLETED)] })
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isTaskPending).toBe(false)
            expect(logic.values.isRunPending).toBe(false)
            expect(logic.values.isHeaderLoading).toBe(false)
            logic.unmount()
        })

        it('resolves immediately for a task that has never run (no perpetual skeleton)', async () => {
            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.runs).toEqual([])
            expect(logic.values.isRunPending).toBe(false)
            expect(logic.values.isHeaderLoading).toBe(false)
            logic.unmount()
        })
    })

    describe('loadTaskSuccess updates tasksLogic', () => {
        it('updates sidebar tasks list when task loads', async () => {
            const tasksLogicInstance = tasksLogic()
            tasksLogicInstance.mount()
            const mockTask = createMockTask('task-123')
            tasksLogicInstance.actions.loadTasksSuccess([mockTask])

            const logic = taskDetailSceneLogic({ taskId: 'task-123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const updatedTask = { ...mockTask, title: 'New Title' }
            logic.actions.loadTaskSuccess(updatedTask)
            await expectLogic(logic).toFinishAllListeners()

            expect(tasksLogicInstance.values.tasks.find((t) => t.id === 'task-123')?.title).toBe('New Title')

            logic.unmount()
            tasksLogicInstance.unmount()
        })
    })
})
