import { initKeaTests } from '~/test/init'

import { OriginProduct, Task } from '../types'
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
})

describe('tasksLogic', () => {
    let logic: ReturnType<typeof tasksLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = tasksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('updateTask', () => {
        it('replaces task in list', () => {
            const task1 = createMockTask('task-1')
            const task2 = createMockTask('task-2')
            logic.actions.loadTasksSuccess([task1, task2])

            const updatedTask = { ...task1, title: 'Updated Title' }
            logic.actions.updateTask(updatedTask)

            expect(logic.values.tasks.find((t) => t.id === 'task-1')?.title).toBe('Updated Title')
            expect(logic.values.tasks).toHaveLength(2)
        })

        it('does not add task if not already in list', () => {
            const task1 = createMockTask('task-1')
            logic.actions.loadTasksSuccess([task1])

            const unknownTask = createMockTask('unknown')
            logic.actions.updateTask(unknownTask)

            expect(logic.values.tasks).toHaveLength(1)
            expect(logic.values.tasks[0].id).toBe('task-1')
        })
    })
})
