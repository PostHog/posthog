import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'

import { RunLogSkeleton } from 'products/posthog_ai/frontend/api/primitives'

import { NETWORK_LOAD_ERROR_MESSAGE } from '../../../lib/load-error'
import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { TaskLoadErrorState } from './TaskLoadErrorState'
import { TaskRunChat } from './TaskRunChat'

/**
 * Run-log slot state machine. Reads `taskDetailSceneLogic` directly (no prop drilling) and resolves to
 * exactly one of: an error state, a `NotFound`, the shared `RunLogSkeleton`, an empty state, or the live
 * `TaskRunChat`. The skeleton is the only loading affordance here — once it hands off to `TaskRunChat`, the
 * eager `RunSurface` shows the same `RunLogSkeleton` during its own bootstrap, so the transition is seamless.
 */
export function TaskRunLog({
    taskId,
    optimisticStreamKey,
    optimisticRunId,
    interactionKey,
    autoFocus,
}: {
    taskId: string
    /** Client `streamKey` of an optimistic-create stream to adopt — set only during the create handoff. */
    optimisticStreamKey?: string
    /** Run id created by the optimistic flow, before the runs list has loaded it. */
    optimisticRunId?: string
    interactionKey?: string
    autoFocus?: boolean
}): JSX.Element | null {
    const logic = taskDetailSceneLogic({ taskId })
    const {
        runs,
        selectedRun,
        selectedRunId,
        loadError,
        isRetryingLoad,
        selectedRunNotFound,
        isRunPending,
        runContinuation,
    } = useValues(logic)
    const { retryLoad, clearContinuationDraft } = useActions(logic)

    if (runContinuation && selectedRunId === runContinuation.run.id) {
        return (
            <div className="flex-1 min-h-0">
                <TaskRunChat
                    taskId={taskId}
                    runId={runContinuation.run.id}
                    streamKey={runContinuation.streamKey}
                    initialDraft={runContinuation.draft}
                    onDraftAdopted={() => clearContinuationDraft(runContinuation.run.id)}
                />
            </div>
        )
    }

    // Optimistic-create handoff: render the run immediately on the seeded stream, bypassing the runs-list
    // load (no skeleton re-flash). `selectedRunId ?? optimisticRunId` tracks the live id — the created run
    // up front, then `selectedRunId` once the runs list resolves it (same id), then any later new run.
    const effectiveRunId = selectedRunId ?? optimisticRunId
    if (optimisticStreamKey && effectiveRunId) {
        return (
            <div className="flex-1 min-h-0">
                <TaskRunChat
                    taskId={taskId}
                    runId={effectiveRunId}
                    streamKey={optimisticStreamKey}
                    interactionKey={effectiveRunId === optimisticRunId ? interactionKey : undefined}
                    autoFocus={effectiveRunId === optimisticRunId && autoFocus}
                />
            </div>
        )
    }

    if (loadError && !selectedRun) {
        return <TaskLoadErrorState message={loadError} onRetry={retryLoad} retrying={isRetryingLoad} />
    }
    if (selectedRunNotFound) {
        return <NotFound object="task run" className="m-0 py-8" />
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
            <>
                {loadError && (
                    <LemonBanner
                        type="warning"
                        className="mx-4 mt-2"
                        action={{
                            children: 'Try again',
                            onClick: retryLoad,
                            loading: isRetryingLoad,
                            'data-attr': 'task-refresh-error-retry',
                        }}
                        data-attr="task-refresh-error"
                    >
                        {loadError === NETWORK_LOAD_ERROR_MESSAGE
                            ? "Can't reach PostHog, so this task may be out of date."
                            : `Couldn't refresh this task. ${loadError}`}
                    </LemonBanner>
                )}
                <div className="flex-1 min-h-0">
                    <TaskRunChat taskId={taskId} runId={selectedRun.id} />
                </div>
            </>
        )
    }
    return selectedRunId ? <RunLogSkeleton /> : null
}
