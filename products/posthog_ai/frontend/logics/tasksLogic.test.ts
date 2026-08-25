import { MOCK_DEFAULT_USER, api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task } from '../types/taskTypes'
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

describe('tasksLogic', () => {
    // Safety net for the test that calls silenceKeaLoadersErrors() inline
    afterEach(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof tasksLogic.build>
    let listRequestUrls: URL[]

    beforeEach(() => {
        listRequestUrls = []
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    listRequestUrls.push(new URL(request.url))
                    return [200, { results: [], count: 0 }]
                },
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
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

    describe('taskListParams', () => {
        it('defaults to "for you"', () => {
            expect(logic.values.assigneeFilter).toBe('for_you')
        })

        // "For you" and "my scouts" both scope to the current user, so they have to split on origin
        // as well as creator, otherwise the two filters return the same rows.
        it.each([
            [
                'for_you' as const,
                { created_by: MOCK_DEFAULT_USER.id, exclude_origin_product: OriginProduct.SIGNALS_SCOUT },
            ],
            ['my_scouts' as const, { created_by: MOCK_DEFAULT_USER.id, origin_product: OriginProduct.SIGNALS_SCOUT }],
            ['team_scouts' as const, { origin_product: OriginProduct.SIGNALS_SCOUT }],
        ])('maps the %s filter to its query params', (assigneeFilter, expected) => {
            logic.actions.setAssigneeFilter(assigneeFilter)

            expect(logic.values.taskListParams).toEqual({ search: undefined, ...expected })
        })

        it('composes the search term with the active assignee filter', () => {
            logic.actions.setSearchQuery('checkout bug')

            expect(logic.values.taskListParams).toEqual({
                search: 'checkout bug',
                created_by: userLogic.values.user?.id,
                exclude_origin_product: OriginProduct.SIGNALS_SCOUT,
            })
        })
    })

    describe('loadTasks', () => {
        // Regression coverage: `taskLogic` reloads every mounted list after an update or delete
        // without knowing what each one shows. Defaulting those parameterless calls to `{}` swapped
        // the active filter for the whole visible set, so "For you" silently filled with scout tasks.
        it('reloads with the active filter when called with no params', async () => {
            logic.actions.loadTasks()
            await expectLogic(logic).toFinishAllListeners()

            expect(listRequestUrls).toHaveLength(1)
            expect(listRequestUrls[0].searchParams.get('exclude_origin_product')).toBe(OriginProduct.SIGNALS_SCOUT)
            expect(listRequestUrls[0].searchParams.get('created_by')).toBe(String(MOCK_DEFAULT_USER.id))
        })
    })

    describe('loadMoreTasks', () => {
        // Regression coverage: `loadMoreTasks` reads `tasksNext` again after its `await`, so a
        // `loadTasks` dispatched while a page is in flight (e.g. a filter change) must not have its
        // state clobbered when the stale page resolves afterwards.
        it('discards a page that resolves after tasksNext has already moved on', async () => {
            const task1 = createMockTask('task-1')
            logic.actions.loadTasksSuccess([task1])
            logic.actions.setTasksNext('/api/projects/1/tasks/?cursor=page-2')

            let resolvePage2: (value: unknown) => void = () => {}
            jest.spyOn(api, 'get').mockImplementationOnce(() => new Promise((resolve) => (resolvePage2 = resolve)))

            logic.actions.loadMoreTasks()
            // A filter change resets the cursor synchronously (via the `loadTasks` reducer) while
            // the page-2 request above is still in flight.
            logic.actions.setTasksNext(null)

            resolvePage2({ results: [createMockTask('stale-page-2-task')], next: null })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tasks).toEqual([task1])
            expect(logic.values.tasksNext).toBeNull()
        })

        // Regression coverage: without clearing `tasksNext` on failure, `hasMore` stays true forever
        // and the infinite-scroll spinner never goes away after a failed page load.
        it('clears tasksNext on failure so the list stops reporting more pages', async () => {
            logic.actions.setTasksNext('/api/projects/1/tasks/?cursor=page-2')
            // Deliberate loader failure — kea-loaders would log it
            silenceKeaLoadersErrors()
            jest.spyOn(api, 'get').mockRejectedValueOnce(new Error('network error'))

            logic.actions.loadMoreTasks()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tasksNext).toBeNull()
            expect(logic.values.tasksLoadingMore).toBe(false)
        })
    })
})
