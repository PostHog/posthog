import { useValues } from 'kea'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { ThreadItem } from '../types/streamTypes'
import { RunAlertActivity } from './RunAlertActivity'

/**
 * An inline run error, with the ids an engineer needs to find the run attached to "Copy details".
 * The closing error reads "Run stopped"; an error the agent recovered from mid-run keeps a softer title.
 */
export function RunErrorRow({ item, isLast }: { item: ThreadItem; isLast: boolean }): JSX.Element {
    const { bootstrappedRunId, bootstrappedTaskId, latestTurnTraceId } = useValues(runStreamLogic)
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
        bootstrappedRunId ? `Run ${bootstrappedRunId}` : null,
        latestTurnTraceId ? `Trace ${latestTurnTraceId}` : null,
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
