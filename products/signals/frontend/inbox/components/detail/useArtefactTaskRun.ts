import { useEffect, useState } from 'react'

import api from 'lib/api'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { isCustomAgentTaskRun, TaskRunArtefactContent } from './artefactTypes'

export interface ArtefactTaskRunState {
    task: Task | null
    loading: boolean
    error: boolean
    status: TaskRunStatus
    runId: string | null
    replayOnly: boolean
    isCustom: boolean
}

/** A `task_run` entry's task, resolved lazily, and the run it shows. Shared by `ArtefactTaskRun` and its quill sibling. */
export function useArtefactTaskRun(content: TaskRunArtefactContent, knownTask?: Task | null): ArtefactTaskRunState {
    const [fetchedTask, setFetchedTask] = useState<Task | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)
    const task = knownTask ?? fetchedTask

    useEffect(() => {
        // The detail logic already resolved this task — no need to fetch it again.
        if (knownTask || !content.task_id) {
            return
        }
        setLoading(true)
        let cancelled = false
        api.tasks
            .get(content.task_id)
            .then((result) => {
                if (!cancelled) {
                    setFetchedTask(result)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setError(true)
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
        return () => {
            cancelled = true
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [content.task_id, knownTask])

    const status = task?.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    // Prefer the run the artefact actually recorded; a task that's been re-run has a newer
    // `latest_run`, so falling back to it would show the wrong transcript. A specific older run has
    // an unknown status, so force the static replay rather than opening an SSE stream for it.
    const isHistoricalRun = !!content.run_id && content.run_id !== task?.latest_run?.id
    const runId = content.run_id ?? task?.latest_run?.id ?? null
    const replayOnly = isHistoricalRun || isTerminalRunStatus(task?.latest_run?.status)

    return { task, loading, error, status, runId, replayOnly, isCustom: isCustomAgentTaskRun(content) }
}
