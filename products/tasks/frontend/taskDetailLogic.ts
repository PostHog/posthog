import { actions, afterMount, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { taskDetailLogicType } from './taskDetailLogicType'
import { Task } from './types'

export interface TaskDetailLogicProps {
    taskId: string
}

export const taskDetailLogic = kea<taskDetailLogicType>([
    path(['products', 'tasks', 'taskDetailLogic']),
    props({} as TaskDetailLogicProps),

    actions({
        updateTask: (taskId: string, updates: Partial<Task>) => ({ taskId, updates }),
    }),

    loaders(({ props }) => ({
        task: {
            loadTask: async () => {
                const response = await api.tasks.get(props.taskId)
                return response as Task
            },
            updateTask: async ({ taskId, updates }: { taskId: string; updates: Partial<Task> }) => {
                const response = await api.tasks.update(taskId, updates)
                return response as Task
            },
        },
    })),

    reducers({
        task: {
            updateTask: (state, { updates }) => (state ? { ...state, ...updates } : null),
        },
    }),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
    }),

    listeners(({ actions }) => ({
        updateTask: async ({ taskId, updates }) => {
            actions.updateTask(taskId, updates)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTask()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.loadTask()
        }
    }),
])
