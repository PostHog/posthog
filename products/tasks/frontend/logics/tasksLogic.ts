import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { Task, TaskListParams, TaskUpsertProps } from '../types'
import type { tasksLogicType } from './tasksLogicType'

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'tasks', 'frontend', 'tasksLogic']),

    actions({
        openTask: (taskId: Task['id']) => ({ taskId }),
        updateTask: (task: Task) => ({ task }),
    }),

    loaders(({ values }) => ({
        tasks: [
            [] as Task[],
            {
                loadTasks: async (params: TaskListParams = {}) => {
                    const response = await api.tasks.list(params)
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
    }),

    listeners(() => ({
        openTask: ({ taskId }) => {
            router.actions.push(`/tasks/${taskId}`)
        },
    })),
])
