import { kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'

import { isApiNotFound, loadErrorMessage } from '../lib/load-error'
import { phDebugQueryParams } from '../lib/ph-debug'
import { Task, type TaskUpsertProps } from '../types/taskTypes'
import type { taskLogicType } from './taskLogicType'
import { tasksLogic } from './tasksLogic'

export interface TaskLogicProps {
    taskId: string
}

export const taskLogic = kea<taskLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'taskLogic']),
    props({} as TaskLogicProps),
    key((props) => props.taskId),
    loaders(({ props, values, actions }) => ({
        task: [
            null as Task | null,
            {
                loadTask: async () => {
                    try {
                        return await api.tasks.get(props.taskId, phDebugQueryParams())
                    } catch (errorObject) {
                        actions.loadTaskFailure(loadErrorMessage('', errorObject), errorObject)
                        return isApiNotFound(errorObject) ? null : values.task
                    }
                },
                runTask: async () => {
                    return await api.tasks.run(props.taskId)
                },
                deleteTask: async () => {
                    await api.tasks.delete(props.taskId)
                    tasksLogic.findAllMounted().forEach((logic) => logic.actions.loadTasks())
                    router.actions.push('/tasks')
                    return null
                },
                updateTask: async ({ data }: { data: TaskUpsertProps }) => {
                    const updatedTask = await api.tasks.update(props.taskId, data)
                    tasksLogic.findAllMounted().forEach((logic) => logic.actions.loadTasks())
                    return updatedTask
                },
            },
        ],
    })),
    reducers({
        taskNotFound: [
            false,
            {
                loadTask: () => false,
                loadTaskFailure: (_, { errorObject }) => isApiNotFound(errorObject),
            },
        ],
        taskError: [
            null as string | null,
            {
                loadTask: () => null,
                loadTaskFailure: (_, { error, errorObject }) =>
                    isApiNotFound(errorObject) ? null : loadErrorMessage(error, errorObject),
            },
        ],
    }),
    listeners(({ values }) => ({
        loadTaskSuccess: () => {
            if (values.task) {
                tasksLogic.findMounted()?.actions.updateTask(values.task)
            }
        },
        runTaskSuccess: () => {
            if (values.task) {
                tasksLogic.findMounted()?.actions.updateTask(values.task)
            }
        },
        updateTaskSuccess: () => {
            if (values.task) {
                tasksLogic.findMounted()?.actions.updateTask(values.task)
            }
        },
    })),
])
