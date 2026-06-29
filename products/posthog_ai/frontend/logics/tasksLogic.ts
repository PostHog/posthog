import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { loadErrorMessage } from '../lib/load-error'
import { Task, TaskListParams, TaskUpsertProps } from '../types/taskTypes'
import type { tasksLogicType } from './tasksLogicType'

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'tasksLogic']),

    actions({
        openTask: (taskId: Task['id']) => ({ taskId }),
        updateTask: (task: Task) => ({ task }),
        setSearchQuery: (search: string) => ({ search }),
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
        tasksError: [
            null as string | null,
            {
                loadTasks: () => null,
                loadTasksFailure: (_, { error, errorObject }) => loadErrorMessage(error, errorObject),
            },
        ],
    }),

    listeners(({ actions }) => ({
        openTask: ({ taskId }) => {
            router.actions.push(`/tasks/${taskId}`)
        },
        // Debounce typing before hitting the server; the loader's own `breakpoint` then drops any
        // response that a newer query has already superseded.
        setSearchQuery: async ({ search }, breakpoint) => {
            await breakpoint(300)
            actions.loadTasks({ search: search || undefined })
        },
    })),
])
