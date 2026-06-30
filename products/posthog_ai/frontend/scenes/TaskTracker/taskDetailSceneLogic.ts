import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { ApiError } from 'lib/api'
import { isUUIDLike } from 'lib/utils/guards'

import { phDebugQueryParams } from '../../lib/ph-debug'
import { TaskLogicProps, taskLogic } from '../../logics/taskLogic'
import { tasksLogic } from '../../logics/tasksLogic'
import { TaskRun } from '../../types/taskTypes'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'

export type TaskDetailSceneLogicProps = TaskLogicProps

function isApiNotFound(errorObject: unknown): boolean {
    return errorObject instanceof ApiError && errorObject.status === 404
}

function loadErrorMessage(error: string, errorObject: unknown): string {
    if (error) {
        return error
    }
    if (errorObject instanceof ApiError && (errorObject.detail || errorObject.statusText)) {
        return errorObject.detail || errorObject.statusText || 'Something went wrong.'
    }
    if (errorObject instanceof Error && errorObject.message) {
        return errorObject.message
    }
    return 'Something went wrong.'
}

export const taskDetailSceneLogic = kea<taskDetailSceneLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'taskDetailSceneLogic']),
    props({} as TaskDetailSceneLogicProps),
    key((props) => props.taskId),

    connect((props: TaskDetailSceneLogicProps) => ({
        values: [taskLogic(props), ['task', 'taskLoading', 'taskNotFound', 'taskError']],
        actions: [
            taskLogic(props),
            ['loadTask', 'loadTaskSuccess', 'runTask', 'runTaskSuccess', 'deleteTask', 'updateTask'],
        ],
    })),

    actions({
        setSelectedRunId: (runId: TaskRun['id'] | null, taskId: string) => ({ runId, taskId }),
        updateRun: (run: TaskRun) => ({ run }),
    }),

    reducers(({ props }) => ({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (state, { runId, taskId }) => (taskId === props.taskId ? runId : state),
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                updateRun: (state: TaskRun[], { run }: { run: TaskRun }) =>
                    state.some((existingRun) => existingRun.id === run.id)
                        ? state.map((existingRun) => (existingRun.id === run.id ? run : existingRun))
                        : [run, ...state],
            },
        ],
        runsError: [
            null as string | null,
            {
                loadTaskRuns: () => null,
                loadTaskRunsFailure: (_, { error, errorObject }) => loadErrorMessage(error, errorObject),
            },
        ],
        selectedRunNotFound: [
            false,
            {
                setSelectedRunId: () => false,
                loadSelectedTaskRun: () => false,
                loadSelectedTaskRunFailure: (_, { errorObject }) => isApiNotFound(errorObject),
            },
        ],
        selectedRunError: [
            null as string | null,
            {
                setSelectedRunId: () => null,
                loadSelectedTaskRun: () => null,
                loadSelectedTaskRunFailure: (_, { error, errorObject }) =>
                    isApiNotFound(errorObject) ? null : loadErrorMessage(error, errorObject),
            },
        ],
    })),

    loaders(({ props, values, actions }) => ({
        runs: [
            [] as TaskRun[],
            {
                loadTaskRuns: async () => {
                    try {
                        const response = await api.tasks.runs.list(props.taskId, phDebugQueryParams())
                        return response.results
                    } catch (errorObject) {
                        actions.loadTaskRunsFailure(loadErrorMessage('', errorObject), errorObject)
                        return values.runs
                    }
                },
            },
        ],
        selectedRunData: [
            null as TaskRun | null,
            {
                loadSelectedTaskRun: async () => {
                    if (!values.selectedRunId) {
                        return null
                    }
                    try {
                        const run = await api.tasks.runs.get(props.taskId, values.selectedRunId, phDebugQueryParams())
                        return run ?? null
                    } catch (errorObject) {
                        actions.loadSelectedTaskRunFailure(loadErrorMessage('', errorObject), errorObject)
                        return values.selectedRunData
                    }
                },
            },
        ],
    })),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
        selectedRun: [
            (s) => [s.selectedRunData, s.runs, s.selectedRunId],
            (selectedRunData, runs, selectedRunId): TaskRun | null => {
                if (selectedRunData && selectedRunData.id === selectedRunId) {
                    return selectedRunData
                }
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
        title: [
            (s) => [s.task],
            (task): string => {
                return task?.title || task?.slug || 'Task'
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setSelectedRunId: ({ runId, taskId }) => {
            if (taskId !== props.taskId || !runId) {
                return
            }
            if (values.runs.some((run) => run.id === runId)) {
                return
            }
            actions.loadSelectedTaskRun()
        },
        runTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            if (task?.latest_run) {
                actions.updateRun(task.latest_run)
                actions.setSelectedRunId(task.latest_run.id, props.taskId)
            }
            actions.loadTaskRuns()
        },
        loadTaskRunsSuccess: ({ runs }) => {
            // Default to the latest run. An explicit ?runId deep-link (e.g. from an Inbox signal report)
            // still wins so those links land on the run they reference; we just never write it ourselves.
            const runIdFromUrl = router.values.searchParams.runId
            const targetRunId = runIdFromUrl && isUUIDLike(runIdFromUrl) ? runIdFromUrl : runs[0]?.id
            if (!targetRunId) {
                return
            }
            if (targetRunId !== values.selectedRunId) {
                actions.setSelectedRunId(targetRunId, props.taskId)
            } else if (!runs.some((run) => run.id === targetRunId)) {
                actions.loadSelectedTaskRun()
            }
        },
        loadSelectedTaskRunSuccess: ({ selectedRunData }) => {
            if (selectedRunData) {
                actions.updateRun(selectedRunData)
            }
        },
        loadTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            tasksLogic.findMounted()?.actions.updateTask(task)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTask()
        actions.loadTaskRuns()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.loadTask()
            actions.loadTaskRuns()
        }
    }),
])
