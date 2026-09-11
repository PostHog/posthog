import { useValues } from 'kea'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { ThreadItem } from '../types/streamTypes'
import { RunAlertActivity } from './RunAlertActivity'

/**
 * An inline run error, with the ids an engineer needs to find the run attached to "Copy details".
 * The closing error reads "Run stopped"; an error the agent recovered from mid-run keeps a softer title.
 */
export function RunErrorRow({ item, isLast }: { item: ThreadItem; isLast: boolean }): JSX.Element {
    const { bootstrappedRunId, bootstrappedTaskId, errorTraceIds } = useValues(runStreamLogic)
    // A replayed error from an earlier run in the chain names that run, not the one being viewed.
    const runId = item.sourceRunId ?? bootstrappedRunId
    const traceId = errorTraceIds.get(item.id)
    const kind =
        item.variant === 'crash'
            ? 'agent_crash'
            : item.variant === 'undelivered'
              ? 'message_undelivered'
              : isLast
                ? 'agent_error'
                : 'agent_error_continued'
    const copyDetails = [
        bootstrappedTaskId ? `Task ${bootstrappedTaskId}` : null,
        runId ? `Run ${runId}` : null,
        traceId ? `Trace ${traceId}` : null,
        item.errorMessage ?? null,
    ]
        .filter(Boolean)
        .join('\n')
    return (
        <RunAlertActivity
            id={item.id}
            kind={kind}
            message={item.errorMessage}
            undeliveredMessage={item.undeliveredMessage}
            copyDetails={copyDetails || undefined}
        />
    )
}
