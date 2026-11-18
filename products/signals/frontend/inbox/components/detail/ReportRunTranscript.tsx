import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'

import { RunLogContainer } from './RunLogContainer'

/**
 * A run's transcript, expanded in place under the row that opened it: live while the run works, a
 * static replay once it is terminal.
 */
export function ReportRunTranscript({
    taskId,
    runId,
    replayOnly,
}: {
    taskId: string
    runId: string | null
    replayOnly: boolean
}): JSX.Element {
    return (
        <div className="mt-1.5 mb-1 ml-1.5">
            {runId ? (
                // The viewer's virtualized thread owns scroll, so this box only bounds the height and
                // clips — an `overflow-y-auto` here would nest a second scrollbar. Content is kept off
                // the border via `threadRowClassName`/`threadListClassName`, not padding on this box.
                <RunLogContainer>
                    <ReadonlyRunSurface
                        taskId={taskId}
                        runId={runId}
                        interaction={replayOnly ? 'read-only' : 'live'}
                        threadRowClassName="px-3"
                        threadListClassName="py-3"
                    />
                </RunLogContainer>
            ) : (
                <div className="rounded border border-primary bg-surface-primary px-3 py-2.5 text-xs text-secondary leading-snug">
                    This run hasn't started yet. Its agent log will appear here once it does.
                </div>
            )}
        </div>
    )
}
