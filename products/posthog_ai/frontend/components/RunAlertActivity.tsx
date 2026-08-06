import { IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { RunAlertKind, RunConnectionState } from '../types/streamTypes'
import { Activity } from './ActivityPrimitives'

interface RunAlertActivityProps extends RunConnectionState {
    /** Stable id for the underlying `Activity` (drives markdown substep ids). Defaults per kind. */
    id?: string
}

const TITLES: Record<RunAlertKind, string> = {
    reconnecting: 'Reconnecting to agent',
    connection_failed: 'Connection lost',
    agent_error: 'Agent error',
    agent_crash: 'Agent stopped unexpectedly',
}

/**
 * The single Activity-based card for every run stream/connection alert, used in two places:
 * - the thread footer (selector-driven, `runStreamLogic.runConnectionState`) for the live `reconnecting`
 *   banner (attempt counter + backoff) and its terminal `connection_failed` state, and
 * - inline in the thread (`ThreadRow`) for genuine agent failures (`agent_error` / `agent_crash`).
 *
 * It replaces the old inline red `AssistantFailureMessage` bubble for the sandbox runtime. A failed card's
 * `Activity` body auto-collapses, so the detail message rides the always-visible `children` region (mirrors
 * `ToolActivity`'s failed-error pattern) rather than the collapsible `details`.
 */
export function RunAlertActivity({ kind, id, attempt, maxAttempts, message }: RunAlertActivityProps): JSX.Element {
    const activityId = id ?? `run-alert-${kind}`

    if (kind === 'reconnecting') {
        const subtitle = attempt && maxAttempts ? `Attempt ${attempt} of ${maxAttempts}` : 'Attempting to reconnect…'
        return (
            <Activity
                id={activityId}
                title={TITLES.reconnecting}
                subtitle={subtitle}
                status="in_progress"
                icon={<Spinner className="size-3" />}
            />
        )
    }

    return (
        <Activity
            id={activityId}
            title={TITLES[kind]}
            status="failed"
            icon={<IconWarning className="size-4 text-danger" />}
            animate={false}
            showCompletionIcon={false}
        >
            {message ? (
                <div className="text-danger">
                    <MarkdownMessage content={message} id={`${activityId}-message`} />
                </div>
            ) : null}
        </Activity>
    )
}
