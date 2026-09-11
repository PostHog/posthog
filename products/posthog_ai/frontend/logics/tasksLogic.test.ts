import { MOCK_DEFAULT_USER, api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task } from '../types/taskTypes'
import { taskHistoryLogic } from './taskHistoryLogic'
import { tasksLogic } from './tasksLogic'

const createMockTask = (id: string): Task => ({
    id,
    task_number: 1,
    slug: `task-${id}`,
    title: `Task ${id}`,
    description: 'A test task',
    origin_product: OriginProduct.USER_CREATED,
    runtime: TaskRuntimeEnumApi.Acp,
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
        // `featureFlags` is a persisted reducer, so a flag set in one test survives the next
        // `initKeaTests` and would make its mount fire an unexpected list load.
        featureFlagLogic.findMounted()?.actions.setFeatureFlags([], {})
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

            // The nav presents recent activity, so every filter must ask the server for it.
            expect(logic.values.taskListParams).toEqual({
                search: undefined,
                ordering: '-last_activity_at',
                ...expected,
            })
        })

        it('composes the search term with the active assignee filter', () => {
            logic.actions.setSearchQuery('checkout bug')

            expect(logic.values.taskListParams).toEqual({
                search: 'checkout bug',
                ordering: '-last_activity_at',
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

        // Regression coverage: the app renders once the feature-flag request times out, so this
        // singleton can mount with the flag still off and `afterMount` never runs again. Without a
        // load on the late flag the nav sits on an empty list and reports "no tasks".
        it('loads once when the task flag arrives after mount', async () => {
            expect(listRequestUrls).toHaveLength(0)

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TASKS], { [FEATURE_FLAGS.TASKS]: true })
            await expectLogic(logic).toFinishAllListeners()

            expect(listRequestUrls).toHaveLength(1)

            // `onFeatureFlags` fires again on any later flag refresh; that must not re-request.
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TASKS], { [FEATURE_FLAGS.TASKS]: true })
            await expectLogic(logic).toFinishAllListeners()

            expect(listRequestUrls).toHaveLength(1)
        })
    })

    describe('setSearchQuery', () => {
        // Regression coverage: the request sits behind a 300ms debounce, so `tasksLoading` is still
        // false while a consumer filters the cached rows against the new query. Without a pending
        // flag the nav reports "nothing found" for a search whose matches are still on the server.
        it('stays pending across the debounce until the matching page lands', async () => {
            logic.actions.loadTasksSuccess([createMockTask('task-1')])

            logic.actions.setSearchQuery('checkout bug')

            expect(logic.values.tasksSearchPending).toBe(true)
            expect(logic.values.tasksLoading).toBe(false)

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tasksSearchPending).toBe(false)
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

        // Regression coverage: the cursor is what renders the manual "Load more" control, so dropping
        // it on a transient failure would remove the only retry for the rest of the session.
        it('keeps tasksNext on failure so the page can be retried', async () => {
            const cursor = '/api/projects/1/tasks/?cursor=page-2'
            logic.actions.setTasksNext(cursor)
            // Deliberate loader failure — kea-loaders would log it
            silenceKeaLoadersErrors()
            jest.spyOn(api, 'get').mockRejectedValueOnce(new Error('network error'))

            logic.actions.loadMoreTasks()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tasksNext).toBe(cursor)
            expect(logic.values.tasksLoadingMore).toBe(false)

            // The retry reuses the same cursor and succeeds.
            resumeKeaLoadersErrors()
            jest.spyOn(api, 'get').mockResolvedValueOnce({ results: [createMockTask('task-2')], next: null })

            logic.actions.loadMoreTasks()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.tasks.map((t) => t.id)).toEqual(['task-2'])
            expect(logic.values.tasksNext).toBeNull()
        })
    })

    describe('deleteTask', () => {
        // Regression coverage: archiving from the shared navigation used to leave the row on the
        // panel history, which loads its own list and never hears about the delete.
        it('drops the task from a mounted panel history', async () => {
            jest.spyOn(api, 'delete').mockResolvedValueOnce({})
            const historyLogic = taskHistoryLogic()
            historyLogic.mount()
            // Let the mount-time load land first, or it overwrites the seeded history.
            await expectLogic(historyLogic).toDispatchActions(['loadHistorySuccess'])
            const task = createMockTask('task-1')
            historyLogic.actions.loadHistorySuccess([task, createMockTask('task-2')])

            logic.actions.deleteTask({ taskId: task.id })
            await expectLogic(logic).toFinishAllListeners()

            expect(historyLogic.values.history.map((t) => t.id)).toEqual(['task-2'])
            historyLogic.unmount()
        })
    })
})
