import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { taskDetailLogic } from './taskDetailLogic'
import { OriginProduct, Task, TaskRun, TaskRunStatus } from './types'

jest.mock('lib/api')

describe('taskDetailLogic', () => {
    let logic: ReturnType<typeof taskDetailLogic.build>

    const mockTask: Task = {
        id: 'task-1',
        task_number: 1,
        slug: 'TSK-1',
        title: 'Test Task',
        description: 'Test Description',
        origin_product: OriginProduct.USER_CREATED,
        repository: 'posthog/posthog',
        github_integration: 1,
        latest_run: null,
        created_at: '2025-01-01T00:00:00Z',
        updated_at: '2025-01-01T00:00:00Z',
        created_by: {
            id: 1,
            uuid: 'user-1',
            distinct_id: 'user-1',
            first_name: 'John',
            email: 'john@example.com',
        },
    }

    const mockRuns: TaskRun[] = [
        {
            id: 'run-1',
            task: 'task-1',
            stage: 'build',
            branch: 'main',
            status: TaskRunStatus.COMPLETED,
            log_url: 'https://s3.example.com/logs/run-1.jsonl',
            error_message: null,
            output: { pr_url: 'https://github.com/posthog/posthog/pull/123' },
            state: {},
            created_at: '2025-01-01T00:00:00Z',
            updated_at: '2025-01-01T00:00:00Z',
            completed_at: '2025-01-01T00:00:00Z',
        },
        {
            id: 'run-2',
            task: 'task-1',
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
    ]

    const mockLogs = JSON.stringify({ timestamp: '2025-01-01T00:00:00Z', level: 'info', message: 'Test log' })

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.tasks, 'get').mockResolvedValue(mockTask as any)
        jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.tasks.runs, 'getLogs').mockResolvedValue('')
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('initialization', () => {
        it('loads task and runs on mount', async () => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTask', 'loadRuns']).toFinishAllListeners()

            expect(api.tasks.get).toHaveBeenCalledWith('task-1')
            expect(api.tasks.runs.list).toHaveBeenCalledWith('task-1')
        })

        it('loads task and runs when taskId changes', async () => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            jest.clearAllMocks()

            const newLogic = taskDetailLogic({ taskId: 'task-2' })
            newLogic.mount()

            await expectLogic(newLogic).toDispatchActions(['loadTask', 'loadRuns']).toFinishAllListeners()

            expect(api.tasks.get).toHaveBeenCalledWith('task-2')
            expect(api.tasks.runs.list).toHaveBeenCalledWith('task-2')
        })
    })

    describe('run selection', () => {
        beforeEach(() => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()
        })

        it('auto-selects latest run on load', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            })
                .toDispatchActions(['loadRunsSuccess'])
                .toMatchValues({
                    selectedRunId: 'run-1',
                    selectedRun: mockRuns[0],
                })
        })

        it('allows manual run selection', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            }).toFinishAllListeners()

            expectLogic(logic, () => {
                logic.actions.setSelectedRunId('run-2')
            }).toMatchValues({
                selectedRunId: 'run-2',
                selectedRun: mockRuns[1],
            })
        })

        it('loads logs when run is selected', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)
            jest.spyOn(api.tasks.runs, 'getLogs').mockResolvedValue(mockLogs)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSelectedRunId('run-1')
            })
                .toDispatchActions(['loadLogs'])
                .toFinishAllListeners()

            expect(api.tasks.runs.getLogs).toHaveBeenCalledWith('task-1', 'run-1')
        })
    })

    describe('canEditRepository', () => {
        beforeEach(() => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()
        })

        it('allows editing when no runs exist', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: [] } as any)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    canEditRepository: true,
                })
        })

        it('prevents editing when runs exist', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    canEditRepository: false,
                })
        })
    })

    describe('runTask', () => {
        beforeEach(() => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()
        })

        it('runs task and reloads data', async () => {
            const updatedTask = { ...mockTask, latest_run: mockRuns[0] }
            jest.spyOn(api.tasks, 'run').mockResolvedValue(updatedTask as any)

            await expectLogic(logic, () => {
                logic.actions.runTask()
            })
                .toDispatchActions(['runTaskSuccess', 'loadTask', 'loadRuns'])
                .toFinishAllListeners()

            expect(api.tasks.run).toHaveBeenCalledWith('task-1')
        })
    })

    describe('deleteTask', () => {
        beforeEach(() => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()
        })

        it('deletes task and navigates to list', async () => {
            jest.spyOn(api.tasks, 'delete').mockResolvedValue(undefined as any)

            await expectLogic(logic, () => {
                logic.actions.deleteTask()
            })
                .toDispatchActions(['deleteTaskSuccess'])
                .toMatchValues({
                    task: null,
                })

            expect(api.tasks.delete).toHaveBeenCalledWith('task-1')
        })
    })

    describe('log loading', () => {
        beforeEach(() => {
            logic = taskDetailLogic({ taskId: 'task-1' })
            logic.mount()
        })

        it('loads logs for selected run', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)
            jest.spyOn(api.tasks.runs, 'getLogs').mockResolvedValue(mockLogs)

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadLogs()
            }).toMatchValues({
                logs: mockLogs,
                logsLoading: false,
            })
        })

        it('returns empty string when no run is selected', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadLogs()
            }).toMatchValues({
                logs: '',
            })
        })

        it('handles log loading errors gracefully', async () => {
            jest.spyOn(api.tasks.runs, 'list').mockResolvedValue({ results: mockRuns } as any)
            jest.spyOn(api.tasks.runs, 'getLogs').mockRejectedValue(new Error('Failed to load logs'))
            const consoleSpy = jest.spyOn(console, 'error').mockImplementation()

            await expectLogic(logic, () => {
                logic.actions.loadRuns()
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadLogs()
            }).toMatchValues({
                logs: '',
            })

            expect(consoleSpy).toHaveBeenCalledWith('Failed to load logs:', expect.any(Error))
            consoleSpy.mockRestore()
        })
    })
})
