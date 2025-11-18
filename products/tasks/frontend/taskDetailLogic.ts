import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { taskDetailLogicType } from './taskDetailLogicType'
import { Task, TaskRun, TaskUpsertProps } from './types'

export interface TaskDetailLogicProps {
    taskId: string
}

export const taskDetailLogic = kea<taskDetailLogicType>([
    path(['products', 'tasks', 'taskDetailLogic']),
    props({} as TaskDetailLogicProps),
    key((props) => props.taskId),

    actions({
        setSelectedRunId: (runId: TaskRun['id'] | null) => ({ runId }),
        runTask: true,
        deleteTask: true,
        updateTask: (data: TaskUpsertProps) => ({ data }),
    }),

    reducers({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (_, { runId }) => runId,
                loadRunsSuccess: (state, { runs }) => {
                    if (state) {
                        return state
                    }
                    return runs.length > 0 ? runs[0].id : null
                },
            },
        ],
    }),

    loaders(({ props, values }) => ({
        task: [
            null as Task | null,
            {
                loadTask: async () => {
                    const response = await api.tasks.get(props.taskId)
                    return response
                },
                runTask: async () => {
                    try {
                        const response = await api.tasks.run(props.taskId)
                        lemonToast.success('Task run started')
                        return response
                    } catch (error) {
                        lemonToast.error('Failed to start task run')
                        throw error
                    }
                },
                deleteTask: async () => {
                    await api.tasks.delete(props.taskId)
                    lemonToast.success('Task deleted')
                    router.actions.push('/tasks')
                    return null
                },
                updateTask: async ({ data }) => {
                    try {
                        const response = await api.tasks.update(props.taskId, data)
                        lemonToast.success('Task updated')
                        return response
                    } catch (error) {
                        lemonToast.error('Failed to update task')
                        throw error
                    }
                },
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                loadRuns: async () => {
                    const response = await api.tasks.runs.list(props.taskId)
                    return response.results
                },
            },
        ],
        logs: [
            '' as string,
            {
                loadLogs: async () => {
                    if (!values.selectedRunId) {
                        return ''
                    }
                    try {
                        return await api.tasks.runs.getLogs(props.taskId, values.selectedRunId)
                    } catch (error) {
                        console.error('Failed to load logs:', error)
                        return ''
                    }
                },
            },
        ],
    })),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
        selectedRun: [
            (s) => [s.runs, s.selectedRunId],
            (runs, selectedRunId): TaskRun | null => {
                if (!selectedRunId) {
                    return null
                }
                return runs.find((run) => run.id === selectedRunId) ?? null
            },
        ],
        canEditRepository: [
            (s) => [s.runs],
            (runs): boolean => {
                return runs.length === 0
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setSelectedRunId: () => {
            actions.loadLogs()
        },
        runTaskSuccess: () => {
            actions.loadTask()
            actions.loadRuns()
        },
        loadRunsSuccess: () => {
            if (values.selectedRunId) {
                actions.loadLogs()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTask()
        actions.loadRuns()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.loadTask()
            actions.loadRuns()
        }
    }),
])
