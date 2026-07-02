import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'

import { RunLogSkeleton } from 'products/posthog_ai/frontend/api/primitives'

import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { TaskErrorBanner } from './TaskErrorBanner'
import { TaskRunChat } from './TaskRunChat'

/**
 * Run-log slot state machine. Reads `taskDetailSceneLogic` directly (no prop drilling) and resolves to
 * exactly one of: an error banner, a `NotFound`, the shared `RunLogSkeleton`, an empty state, or the live
 * `TaskRunChat`. The skeleton is the only loading affordance here — once it hands off to `TaskRunChat`, the
 * eager `RunSurface` shows the same `RunLogSkeleton` during its own bootstrap, so the transition is seamless.
 */
export function TaskRunLog({
    taskId,
    optimisticStreamKey,
    optimisticRunId,
}: {
    taskId: string
    /** Client `streamKey` of an optimistic-create stream to adopt — set only during the create handoff. */
    optimisticStreamKey?: string
    /** Run id created by the optimistic flow, before the runs list has loaded it. */
    optimisticRunId?: string
}): JSX.Element | null {
    const logic = taskDetailSceneLogic({ taskId })
    const { runs, selectedRun, selectedRunId, runsError, selectedRunError, selectedRunNotFound, isRunPending } =
        useValues(logic)
    const { loadTaskRuns, loadSelectedTaskRun } = useActions(logic)

    // Optimistic-create handoff: render the run immediately on the seeded stream, bypassing the runs-list
    // load (no skeleton re-flash). `selectedRunId ?? optimisticRunId` tracks the live id — the created run
    // up front, then `selectedRunId` once the runs list resolves it (same id), then any later new run.
    const effectiveRunId = selectedRunId ?? optimisticRunId
    if (optimisticStreamKey && effectiveRunId) {
        return (
            <div className="flex-1 min-h-0">
                <TaskRunChat taskId={taskId} runId={effectiveRunId} streamKey={optimisticStreamKey} />
            </div>
        )
    }

    if (runsError) {
        return (
            <TaskErrorBanner
                title="We couldn't load this task's runs."
                message={runsError}
                onRetry={loadTaskRuns}
                dataAttr="task-runs-load-error"
            />
        )
    }
    if (selectedRunError) {
        return (
            <TaskErrorBanner
                title="We couldn't load this task's runs."
                message={selectedRunError}
                onRetry={loadSelectedTaskRun}
                dataAttr="task-runs-load-error"
            />
        )
    }
    if (selectedRunNotFound) {
        // Reached via a ?runId deep-link (e.g. a Slack "task failed" link) that no longer resolves. The generic
        // "deleted / sharing settings changed" copy is misleading for a run — name the id and the real causes.
        return (
            <NotFound
                object="task run"
                className="m-0 py-8"
                caption={
                    <>
                        We couldn't find this run on the task.
                        {selectedRunId ? (
                            <>
                                <br />
                                Run ID: <span className="font-mono">{selectedRunId}</span>
                            </>
                        ) : null}
                        <br />
                        <br />
                        The run may belong to a different task, or it failed before it was recorded. Pick another run
                        from the list, or check the run's Temporal workflow for the underlying error.
                    </>
                }
            />
        )
    }
    if (isRunPending) {
        return <RunLogSkeleton />
    }
    if (runs.length === 0 && !selectedRunId) {
        return (
            <div className="text-center py-16">
                <p className="text-muted">This task hasn't been run yet</p>
            </div>
        )
    }
    if (selectedRun) {
        // The viewer owns scroll edge-to-edge; this box just bounds the height. No `overflow-hidden`/negative
        // margins — content is kept off the scrollbar via the viewer's `threadRowClassName`, not by clipping here.
        return (
            <div className="flex-1 min-h-0">
                <TaskRunChat taskId={taskId} runId={selectedRun.id} />
            </div>
        )
    }
    return selectedRunId ? <RunLogSkeleton /> : null
}
