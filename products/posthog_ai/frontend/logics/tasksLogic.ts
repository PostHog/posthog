import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { loadErrorMessage } from '../lib/load-error'
import { OriginProduct, Task, TaskAssigneeFilter, TaskListParams, TaskUpsertProps } from '../types/taskTypes'
import type { tasksLogicType } from './tasksLogicType'

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'tasksLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
    })),

    actions({
        openTask: (taskId: Task['id']) => ({ taskId }),
        updateTask: (task: Task) => ({ task }),
        setSearchQuery: (search: string) => ({ search }),
        setAssigneeFilter: (assigneeFilter: TaskAssigneeFilter) => ({ assigneeFilter }),
        setTasksNext: (next: string | null) => ({ next }),
    }),

    loaders(({ actions, values }) => ({
        tasks: [
            [] as Task[],
            {
                // `breakpoint` cancels this invocation if a newer `loadTasks` action has been
                // dispatched, so filter changes don't overwrite state with stale responses.
                loadTasks: async (params: TaskListParams = {}, breakpoint) => {
                    const response = await api.tasks.list(params)
                    breakpoint()
                    actions.setTasksNext(response.next ?? null)
                    return response.results
                },
                // Appends the next page for infinite scroll. The cursor is the absolute `next`
                // URL from the previous response, so it carries the active filters forward.
                loadMoreTasks: async (_: void, breakpoint) => {
                    const next = values.tasksNext
                    if (!next) {
                        return values.tasks
                    }
                    // `next` is an opaque absolute cursor URL from the previous response, not a static
                    // endpoint — the generated `tasksList` takes structured params, not a raw URL.
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<PaginatedResponse<Task>>(next)
                    breakpoint()
                    // `breakpoint` only cancels a second `loadMoreTasks` call, not a `loadTasks` triggered
                    // by a filter change while this page was in flight. A fresh `loadTasks` resets
                    // `tasksNext` to null synchronously on dispatch, so a mismatch here means this page
                    // belongs to a filter that's no longer active — discard it instead of appending.
                    if (values.tasksNext !== next) {
                        return values.tasks
                    }
                    actions.setTasksNext(response.next ?? null)
                    return [...values.tasks, ...response.results]
                },
                createTask: async ({ data }: { data: TaskUpsertProps }) => {
                    const newTask = await api.tasks.create(data)
                    void addProductIntent({
                        product_type: ProductKey.TASKS,
                        intent_context: ProductIntentContext.TASK_CREATED,
                    })
                    return [...values.tasks, newTask]
                },
                deleteTask: async ({ taskId }: { taskId: string }) => {
                    await api.tasks.delete(taskId)
                    return values.tasks.filter((t) => t.id !== taskId)
                },
            },
        ],
        repositories: [
            [] as string[],
            {
                // Repositories are loaded via a dedicated endpoint instead of being derived
                // from `tasks` so the picker is not constrained by list pagination or by the
                // filter currently applied to the task list.
                loadRepositories: async () => {
                    const response = await api.tasks.repositories()
                    return response.repositories
                },
            },
        ],
    })),

    reducers({
        tasks: {
            updateTask: (state, { task }) => state.map((t) => (t.id === task.id ? task : t)),
        },
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { search }) => search,
            },
        ],
        assigneeFilter: [
            'for_you' as TaskAssigneeFilter,
            {
                setAssigneeFilter: (_, { assigneeFilter }) => assigneeFilter,
            },
        ],
        tasksError: [
            null as string | null,
            {
                loadTasks: () => null,
                loadTasksFailure: (_, { error, errorObject }) => loadErrorMessage(error, errorObject),
            },
        ],
        // Cursor for the next page; null once the list is exhausted. Reset on every fresh load so a
        // filter/search change starts from page one.
        tasksNext: [
            null as string | null,
            {
                loadTasks: () => null,
                setTasksNext: (_, { next }) => next,
                // Clear the cursor on failure too, otherwise `hasMore` stays true forever and the
                // infinite-scroll spinner keeps spinning with no feedback that the request failed.
                loadMoreTasksFailure: () => null,
            },
        ],
        // Distinct from `tasksLoading` (which also flips for `loadMoreTasks`) so the infinite-scroll
        // trigger can guard against firing again while a page is already in flight.
        tasksLoadingMore: [
            false,
            {
                loadMoreTasks: () => true,
                loadMoreTasksSuccess: () => false,
                loadMoreTasksFailure: () => false,
            },
        ],
    }),

    selectors({
        // Combined list filters: search term + the assignee toggle. "For you" scopes to the current
        // user's own tasks; "team scouts" scopes to autonomous Signals Scout tasks.
        taskListParams: [
            (s) => [s.searchQuery, s.assigneeFilter, s.user],
            (searchQuery, assigneeFilter, user): TaskListParams => ({
                search: searchQuery || undefined,
                ...(assigneeFilter === 'for_you'
                    ? { created_by: user?.id }
                    : { origin_product: OriginProduct.SIGNALS_SCOUT }),
            }),
        ],
    }),

    listeners(({ actions, values }) => ({
        openTask: ({ taskId }) => {
            router.actions.push(`/tasks/${taskId}`)
        },
        // Debounce typing before hitting the server; the loader's own `breakpoint` then drops any
        // response that a newer query has already superseded.
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadTasks(values.taskListParams)
        },
        setAssigneeFilter: () => {
            actions.loadTasks(values.taskListParams)
        },
        loadMoreTasksFailure: ({ error, errorObject }) => {
            lemonToast.error(`Couldn't load more tasks: ${loadErrorMessage(error, errorObject)}`)
        },
    })),
])
