import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { identifierToHuman } from 'lib/utils/strings'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { ActivityDisclosure } from './ActivityDisclosure'
import { isCustomAgentTaskRun, taskRunTypeLabel, TaskRunArtefactContent } from './artefactTypes'
import { RunLogContainer } from './RunLogContainer'

type TaskLoadError = 'unavailable' | 'failed'

/**
 * A `task_run` artefact: the linked task badged from its `(product, type)` (signals-pipeline runs
 * show Research / Implementation / Repo selection; custom agents show their humanized product +
 * type), expanding to the task's run transcript via the shared `ReadonlyRunSurface`. Mirrors desktop
 * `ArtefactTaskRun` (which embeds `TaskLogsPanel`). The task is resolved lazily and the row is
 * disabled until it loads.
 */
export function ArtefactTaskRun({
    content,
    knownTask,
}: {
    content: TaskRunArtefactContent
    /** The resolved task, when the detail logic already fetched it (research/implementation runs) —
     * lets the row skip a redundant `GET /tasks/{id}`. Falls back to a lazy fetch otherwise. */
    knownTask?: Task | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [fetchedTask, setFetchedTask] = useState<Task | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<TaskLoadError | null>(null)
    const [attempt, setAttempt] = useState(0)
    const task = knownTask ?? fetchedTask

    useEffect(() => {
        // The detail logic already resolved this task — no need to fetch it again.
        if (knownTask || !content.task_id) {
            return
        }
        setLoading(true)
        setError(null)
        setFetchedTask(null)
        let cancelled = false
        api.tasks
            .get(content.task_id)
            .then((result) => {
                if (!cancelled) {
                    setFetchedTask(result)
                }
            })
            .catch((e) => {
                if (!cancelled) {
                    // The API answers 404 for a task the reader can't see (e.g. filed into a
                    // channel they aren't in), so retrying won't help there.
                    const status = e instanceof ApiError ? e.status : undefined
                    setError(status === 404 || status === 403 ? 'unavailable' : 'failed')
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
    }, [content.task_id, knownTask, attempt])

    const status = task?.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    // Prefer the run the artefact actually recorded; a task that's been re-run has a newer
    // `latest_run`, so falling back to it would show the wrong transcript. A specific older run has
    // an unknown status, so force the static replay rather than opening an SSE stream for it.
    const isHistoricalRun = !!content.run_id && content.run_id !== task?.latest_run?.id
    const runId = content.run_id ?? task?.latest_run?.id ?? null
    const replayOnly = isHistoricalRun || isTerminalRunStatus(task?.latest_run?.status)
    const isCustom = isCustomAgentTaskRun(content)

    return (
        <div>
            <ActivityDisclosure
                expanded={expanded}
                onChange={setExpanded}
                disabledReason={
                    !task
                        ? error === 'unavailable'
                            ? "You don't have access to this task"
                            : error
                              ? "Couldn't load this task"
                              : 'Task details are loading'
                        : undefined
                }
                fullWidth
                label={
                    <span className="flex min-w-0 items-center gap-2">
                        <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                        <LemonTag size="small" type="muted">
                            {taskRunTypeLabel(content)}
                        </LemonTag>
                        {isCustom ? (
                            <LemonTag size="small" type="completion">
                                {identifierToHuman(content.product)}
                            </LemonTag>
                        ) : null}
                        {loading ? (
                            <LemonSkeleton className="h-3 w-32" />
                        ) : (
                            <span className="truncate text-secondary">{task?.title ?? content.task_id}</span>
                        )}
                    </span>
                }
                expandedLabel={
                    <span className="flex min-w-0 items-center gap-2">
                        <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                        <span className="truncate text-secondary">Hide task run</span>
                    </span>
                }
            >
                {task && runId ? (
                    <RunLogContainer>
                        <ReadonlyRunSurface
                            taskId={task.id}
                            runId={runId}
                            interaction={replayOnly ? 'read-only' : 'live'}
                            threadRowClassName="px-3"
                            threadListClassName="py-3"
                        />
                    </RunLogContainer>
                ) : null}
            </ActivityDisclosure>
            {error === 'unavailable' ? (
                <p className="m-0 pl-6 text-xs text-secondary">
                    This task is in a channel you're not a member of, or it was deleted.
                </p>
            ) : error === 'failed' ? (
                <div className="flex items-center gap-2 pl-6 text-xs">
                    <span className="text-danger">Couldn't load this task.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => setAttempt((n) => n + 1)}>
                        Try again
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
