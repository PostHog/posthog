import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { OriginProduct, Task, TaskRunStatus } from '../types'
import { taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const createMockTask = (id: string): Task => ({
    id,
    task_number: 1,
    slug: `task-${id}`,
    title: `Task ${id}`,
    description: 'A test task',
    origin_product: OriginProduct.USER_CREATED,
    repository: 'test/repo',
    github_integration: null,
    latest_run: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: null,
    distinct_user_count: 0,
    occurrence_count: 0,
    last_occurrence_at: null,
    segment_link_count: 0,
})

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
                    log_url: null,
                    error_message: null,
                    output: null,
                    state: {},
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
