import { kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { Task, type TaskUpsertProps } from '../types'
import type { taskLogicType } from './taskLogicType'
import { tasksLogic } from './tasksLogic'

export interface TaskLogicProps {
    taskId: string
}

export const taskLogic = kea<taskLogicType>([
    path(['products', 'tasks', 'taskLogic']),
    props({} as TaskLogicProps),
    key((props) => props.taskId),
    loaders(({ props }) => ({
        task: [
            null as Task | null,
            {
                loadTask: async () => {
                    return await api.tasks.get(props.taskId)
                },
                runTask: async () => {
                    const response = await api.tasks.run(props.taskId)
                    lemonToast.success('Task run started')
                    return response
                },
                deleteTask: async () => {
                    await api.tasks.delete(props.taskId)
                    lemonToast.success('Task archived')
                    tasksLogic.findAllMounted().forEach((logic) => logic.actions.loadTasks())
                    router.actions.push('/tasks')
                    return null
                },
                updateTask: async ({ data }: { data: TaskUpsertProps }) => {
                    const updatedTask = await api.tasks.update(props.taskId, data)
                    lemonToast.success('Task updated')
                    tasksLogic.findAllMounted().forEach((logic) => logic.actions.loadTasks())
                    return updatedTask
                },
            },
        ],
    })),
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
