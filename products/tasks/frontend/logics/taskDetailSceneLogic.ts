import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { phDebugQueryParams } from '../lib/ph-debug'
import { TaskRun } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

export type TaskDetailSceneLogicProps = TaskLogicProps

export const taskDetailSceneLogic = kea<taskDetailSceneLogicType>([
    path(['products', 'tasks', 'taskDetailSceneLogic']),
    props({} as TaskDetailSceneLogicProps),
    key((props) => props.taskId),

    connect((props: TaskDetailSceneLogicProps) => ({
        values: [taskLogic(props), ['task', 'taskLoading']],
        actions: [
            taskLogic(props),
            ['loadTask', 'loadTaskSuccess', 'runTask', 'runTaskSuccess', 'deleteTask', 'updateTask'],
        ],
    })),

    actions({
        setSelectedRunId: (runId: TaskRun['id'] | null, taskId: string) => ({ runId, taskId }),
        selectLatestRun: true,
        clearShouldSelectLatestRun: true,
        updateRun: (run: TaskRun) => ({ run }),
    }),

    reducers(({ props }) => ({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (state, { runId, taskId }) => (taskId === props.taskId ? runId : state),
            },
        ],
        shouldSelectLatestRun: [
            false,
            {
                selectLatestRun: () => true,
                clearShouldSelectLatestRun: () => false,
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                updateRun: (state: TaskRun[], { run }: { run: TaskRun }) =>
                    state.map((r) => (r.id === run.id ? run : r)),
            },
        ],
    })),

    loaders(({ props, values }) => ({
        runs: [
            [] as TaskRun[],
            {
                loadRuns: async () => {
                    const response = await api.tasks.runs.list(props.taskId, phDebugQueryParams())
                    return response.results
                },
            },
        ],
        selectedRunData: [
            null as TaskRun | null,
            {
                loadSelectedRun: async () => {
                    if (!values.selectedRunId) {
                        return null
                    }
                    const run = await api.tasks.runs.get(props.taskId, values.selectedRunId, phDebugQueryParams())
                    return run ?? null
                },
            },
        ],
    })),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
        selectedRun: [
            (s) => [s.selectedRunData, s.runs, s.selectedRunId],
            (selectedRunData, runs, selectedRunId): TaskRun | null => {
                if (selectedRunData) {
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
        setSelectedRunId: ({ taskId }) => {
            if (taskId !== props.taskId) {
                return
            }
            actions.loadSelectedRun()
        },
        runTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            if (task?.latest_run) {
                actions.setSelectedRunId(task.latest_run.id, props.taskId)
            }
            actions.loadRuns()
        },
        loadRunsSuccess: ({ runs }) => {
            const shouldSelect = values.shouldSelectLatestRun
            if (shouldSelect) {
                actions.clearShouldSelectLatestRun()
            }
            if (shouldSelect && runs.length > 0) {
                actions.setSelectedRunId(runs[0].id, props.taskId)
            } else if (values.selectedRunId) {
                actions.loadSelectedRun()
            }
        },
        loadSelectedRunSuccess: ({ selectedRunData }) => {
            if (selectedRunData) {
                actions.updateRun(selectedRunData)
            }
            actions.loadTask()
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
        actions.loadRuns()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.loadTask()
            actions.loadRuns()
        }
    }),

    urlToAction(({ actions, values, props }) => ({
        [urls.taskDetail(':taskId')]: (params, searchParams) => {
            const { taskId: urlTaskId } = params
            if (urlTaskId !== props.taskId) {
                return
            }
            const runIdFromUrl = searchParams.runId
            if (runIdFromUrl && isUUIDLike(runIdFromUrl) && runIdFromUrl !== values.selectedRunId) {
                actions.setSelectedRunId(runIdFromUrl, props.taskId)
            }
        },
    })),

    actionToUrl(({ props }) => ({
        setSelectedRunId: ({ runId }) => {
            if (runId) {
                return [urls.taskDetail(props.taskId), { runId }, router.values.hashParams]
            }
            return [urls.taskDetail(props.taskId), {}, router.values.hashParams]
        },
        loadRunsSuccess: ({ runs }) => {
            if (runs.length > 0 && !router.values.searchParams.runId) {
                return [urls.taskDetail(props.taskId), { runId: runs[0].id }, router.values.hashParams]
            }
            return undefined
        },
    })),
])
