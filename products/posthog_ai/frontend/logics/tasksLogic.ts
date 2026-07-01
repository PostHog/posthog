import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
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
    }),

    loaders(({ values }) => ({
        tasks: [
            [] as Task[],
            {
                // `breakpoint` cancels this invocation if a newer `loadTasks` action has been
                // dispatched, so filter changes don't overwrite state with stale responses.
                loadTasks: async (params: TaskListParams = {}, breakpoint) => {
                    const response = await api.tasks.list(params)
                    breakpoint()
                    return response.results
                },
                createTask: async ({ data }: { data: TaskUpsertProps }) => {
                    const newTask = await api.tasks.create(data)
                    lemonToast.success('Task created successfully')
                    void addProductIntent({
                        product_type: ProductKey.TASKS,
                        intent_context: ProductIntentContext.TASK_CREATED,
                    })
                    return [...values.tasks, newTask]
                },
                deleteTask: async ({ taskId }: { taskId: string }) => {
                    await api.tasks.delete(taskId)
                    lemonToast.success('Task deleted')
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
    })),
])
