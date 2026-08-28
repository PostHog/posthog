import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { RuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task, TaskRunEnvironment, TaskRunStatus } from '../types/taskTypes'
import { taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const createMockTask = (id: string): Task => ({
    id,
    task_number: 1,
    slug: `task-${id}`,
    title: `Task ${id}`,
    description: 'A test task',
    origin_product: OriginProduct.USER_CREATED,
    runtime: RuntimeEnumApi.Acp,
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

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: { error: jest.fn(), success: jest.fn() },
}))

describe('taskLogic', () => {
    let logic: ReturnType<typeof taskLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('loadTaskSuccess', () => {
        it('updates tasksLogic with fresh task', async () => {
            const tasksLogicInstance = tasksLogic()
            tasksLogicInstance.mount()
            const mockTask = createMockTask('task-123')
            tasksLogicInstance.actions.loadTasksSuccess([mockTask])

            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            const updatedTask = { ...mockTask, title: 'Updated Title' }
            logic.actions.loadTaskSuccess(updatedTask)
            await expectLogic(logic).toFinishAllListeners()

            expect(tasksLogicInstance.values.tasks.find((t) => t.id === 'task-123')?.title).toBe('Updated Title')
            tasksLogicInstance.unmount()
        })
    })

    describe('loadTaskFailure', () => {
        it('stores not-found failures separately from retryable load errors', () => {
            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.loadTaskFailure('Not found', new ApiError('Not found', 404))

            expect(logic.values.taskNotFound).toBe(true)
            expect(logic.values.taskError).toBe(null)
        })

        it('stores non-404 load failures for inline retry UI', () => {
            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.loadTaskFailure('Could not load task', new ApiError('Could not load task', 500))

            expect(logic.values.taskNotFound).toBe(false)
            expect(logic.values.taskError).toBe('Could not load task')
        })
    })

    describe('runTaskFailure', () => {
        it('surfaces the error and clears the in-flight state so the button is clickable again', async () => {
            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            logic.actions.runTask()
            expect(logic.values.runTaskInFlight).toBe(true)

            logic.actions.runTaskFailure('Sandbox unavailable', new ApiError('Sandbox unavailable', 503))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.runTaskInFlight).toBe(false)
            expect(lemonToast.error).toHaveBeenCalledWith('Sandbox unavailable')
        })
    })

    describe('refreshing task lists after a mutation', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        // A mutation from the detail view reloads every mounted list. A bare `loadTasks()` defaults
        // to `{}`, which drops the active filter — e.g. "For you"'s scout exclusion — and returns the
        // whole visible set until the next filter/search change. The refresh must carry each list's
        // current params.
        it.each([
            ['updateTask', () => logic.actions.updateTask({ data: { title: 'renamed' } })],
            ['deleteTask', () => logic.actions.deleteTask()],
        ])('%s reloads the list with its active filter, not the unfiltered default', async (_name, mutate) => {
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            const listSpy = jest
                .spyOn(api.tasks, 'list')
                .mockResolvedValue({ results: [], count: 0, next: null } as any)
            jest.spyOn(api.tasks, 'update').mockResolvedValue(createMockTask('task-123'))
            jest.spyOn(api.tasks, 'delete').mockResolvedValue(undefined)

            const tasksLogicInstance = tasksLogic()
            tasksLogicInstance.mount()
            tasksLogicInstance.actions.setAssigneeFilter('my_scouts')
            await expectLogic(tasksLogicInstance).toFinishAllListeners()
            listSpy.mockClear()

            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            await expectLogic(tasksLogicInstance, () => {
                mutate()
            }).toDispatchActions(['loadTasks', 'loadTasksSuccess'])

            expect(listSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    created_by: MOCK_DEFAULT_USER.id,
                    origin_product: OriginProduct.SIGNALS_SCOUT,
                })
            )
            tasksLogicInstance.unmount()
        })
    })

    describe('runTaskSuccess', () => {
        it('updates tasksLogic with task including new run', async () => {
            const tasksLogicInstance = tasksLogic()
            tasksLogicInstance.mount()
            const mockTask = createMockTask('task-123')
            tasksLogicInstance.actions.loadTasksSuccess([mockTask])

            logic = taskLogic({ taskId: 'task-123' })
            logic.mount()

            const taskWithRun: Task = {
                ...mockTask,
                latest_run: {
                    id: 'run-456',
                    task: 'task-123',
                    stage: null,
                    branch: null,
                    status: TaskRunStatus.QUEUED,
                    environment: TaskRunEnvironment.CLOUD,
                    runtime_adapter: null,
                    model: null,
                    reasoning_effort: null,
                    log_url: null,
                    error_message: null,
                    output: null,
                    state: {},
                    artifacts: [],
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                    completed_at: null,
                },
            }
            logic.actions.runTaskSuccess(taskWithRun)
            await expectLogic(logic).toFinishAllListeners()

            const updated = tasksLogicInstance.values.tasks.find((t) => t.id === 'task-123')
            expect(updated?.latest_run?.id).toBe('run-456')
            tasksLogicInstance.unmount()
        })
    })
})
