import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tasksLogic } from './tasksLogic'
import { OriginProduct, Task, TaskRunStatus } from './types'

jest.mock('lib/api')

describe('tasksLogic', () => {
    let logic: ReturnType<typeof tasksLogic.build>

    const mockTasks: Task[] = [
        {
            id: '1',
            task_number: 1,
            slug: 'TSK-1',
            title: 'Test Task 1',
            description: 'Description 1',
            origin_product: OriginProduct.USER_CREATED,
            repository: 'posthog/posthog',
            github_integration: 1,
            latest_run: {
                id: 'run-1',
                task: '1',
                stage: 'build',
                branch: 'main',
                status: TaskRunStatus.COMPLETED,
                log_url: null,
                error_message: null,
                output: null,
                state: {},
                created_at: '2025-01-01T00:00:00Z',
                updated_at: '2025-01-01T00:00:00Z',
                completed_at: '2025-01-01T00:00:00Z',
            },
            created_at: '2025-01-01T00:00:00Z',
            updated_at: '2025-01-01T00:00:00Z',
            created_by: {
                id: 1,
                uuid: 'user-1',
                distinct_id: 'user-1',
                first_name: 'John',
                email: 'john@example.com',
            },
        },
        {
            id: '2',
            task_number: 2,
            slug: 'TSK-2',
            title: 'Test Task 2',
            description: 'Description 2',
            origin_product: OriginProduct.USER_CREATED,
            repository: 'posthog/posthog-js',
            github_integration: 1,
            latest_run: {
                id: 'run-2',
                task: '2',
                stage: 'test',
                branch: 'develop',
                status: TaskRunStatus.IN_PROGRESS,
                log_url: null,
                error_message: null,
                output: null,
                state: {},
                created_at: '2025-01-02T00:00:00Z',
                updated_at: '2025-01-02T00:00:00Z',
                completed_at: null,
            },
            created_at: '2025-01-02T00:00:00Z',
            updated_at: '2025-01-02T00:00:00Z',
            created_by: null,
        },
    ]

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: [] } as any)
        logic = tasksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    describe('loadTasks', () => {
        it('loads tasks successfully', async () => {
            jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: mockTasks } as any)

            await expectLogic(logic, () => {
                logic.actions.loadTasks()
            })
                .toDispatchActions(['loadTasksSuccess'])
                .toMatchValues({
                    tasks: mockTasks,
                    tasksLoading: false,
                })
        })
    })

    describe('filtering', () => {
        beforeEach(async () => {
            jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: mockTasks } as any)
            await expectLogic(logic, () => {
                logic.actions.loadTasks()
            }).toFinishAllListeners()
        })

        it('filters by search query - title', () => {
            expectLogic(logic, () => {
                logic.actions.setSearchQuery('Task 1')
            }).toMatchValues({
                filteredTasks: [mockTasks[0]],
            })
        })

        it('filters by search query - slug', () => {
            expectLogic(logic, () => {
                logic.actions.setSearchQuery('TSK-2')
            }).toMatchValues({
                filteredTasks: [mockTasks[1]],
            })
        })

        it('filters by repository', () => {
            expectLogic(logic, () => {
                logic.actions.setRepository('posthog-js')
            }).toMatchValues({
                filteredTasks: [mockTasks[1]],
            })
        })

        it('filters by status', () => {
            expectLogic(logic, () => {
                logic.actions.setStatus(TaskRunStatus.COMPLETED)
            }).toMatchValues({
                filteredTasks: [mockTasks[0]],
            })
        })

        it('combines multiple filters', () => {
            expectLogic(logic, () => {
                logic.actions.setSearchQuery('Test')
                logic.actions.setStatus(TaskRunStatus.IN_PROGRESS)
            }).toMatchValues({
                filteredTasks: [mockTasks[1]],
            })
        })
    })

    describe('repositories selector', () => {
        it('extracts unique repositories', async () => {
            jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: mockTasks } as any)

            await expectLogic(logic, () => {
                logic.actions.loadTasks()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    repositories: ['posthog/posthog', 'posthog/posthog-js'],
                })
        })
    })

    describe('createTask', () => {
        it('creates a task and navigates to it', async () => {
            const newTask: Task = {
                ...mockTasks[0],
                id: '3',
                title: 'New Task',
            }

            jest.spyOn(api.tasks, 'create').mockResolvedValue(newTask as any)

            await expectLogic(logic, () => {
                logic.actions.createTask({
                    title: 'New Task',
                    description: 'Test',
                    origin_product: OriginProduct.USER_CREATED,
                    repository: 'posthog/posthog',
                    github_integration: 1,
                })
            })
                .toDispatchActions(['createTaskSuccess', 'closeCreateModal'])
                .toFinishAllListeners()
        })
    })

    describe('deleteTask', () => {
        beforeEach(async () => {
            jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: mockTasks } as any)
            await expectLogic(logic, () => {
                logic.actions.loadTasks()
            }).toFinishAllListeners()
        })

        it('deletes a task', async () => {
            jest.spyOn(api.tasks, 'delete').mockResolvedValue(undefined as any)

            await expectLogic(logic, () => {
                logic.actions.deleteTask('1')
            })
                .toDispatchActions(['deleteTaskSuccess'])
                .toMatchValues({
                    tasks: [mockTasks[1]],
                })
        })
    })
})
