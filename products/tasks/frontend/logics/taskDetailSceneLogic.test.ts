import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../types'
import { taskDetailSceneLogic } from './taskDetailSceneLogic'
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
    json_schema: null,
    latest_run: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: null,
    relevant_user_count: 0,
    occurrence_count: 0,
    last_occurrence_at: null,
    reference_count: 0,
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

describe('taskDetailSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
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
            logic.actions.loadRunsSuccess([initialRun])
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
            logic.actions.loadRunsSuccess([run1, run2])

            const updatedRun2 = createMockRun('run-2', TaskRunStatus.IN_PROGRESS)
            logic.actions.updateRun(updatedRun2)

            expect(logic.values.runs[0].status).toBe(TaskRunStatus.COMPLETED)
            expect(logic.values.runs[1].status).toBe(TaskRunStatus.IN_PROGRESS)
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

            const updatedTask = { ...mockTask, title: 'New Title' }
            logic.actions.loadTaskSuccess(updatedTask)
            await expectLogic(logic).toFinishAllListeners()

            expect(tasksLogicInstance.values.tasks.find((t) => t.id === 'task-123')?.title).toBe('New Title')

            logic.unmount()
            tasksLogicInstance.unmount()
        })
    })
})
