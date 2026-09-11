import { IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { RunAlertKind, RunConnectionState } from '../types/streamTypes'
import { Activity } from './ActivityPrimitives'

interface RunAlertActivityProps extends RunConnectionState {
    /** Stable id for the markdown message. Defaults per kind. */
    id?: string
    /** A follow-up message failed to reach the agent because of this error. */
    undeliveredMessage?: boolean
    /** Text for the "Copy details" action: run and task ids, trace id, and the reason. */
    copyDetails?: string
}

const TITLES: Record<RunAlertKind, string> = {
    reconnecting: 'Reconnecting to agent',
    connection_failed: 'Connection lost',
    agent_error: 'Run stopped',
    agent_error_continued: 'Agent error',
    agent_crash: 'Agent stopped unexpectedly',
    message_undelivered: 'Message not delivered',
}

/**
 * The card for every run stream/connection alert, used in two places:
 * - the thread footer (selector-driven, `runStreamLogic.runConnectionState`) for the live `reconnecting`
 *   line (attempt counter + backoff) and its terminal `connection_failed` state, and
 * - inline in the thread (`ThreadRow` via `RunErrorRow`) for a stopped run, a crash, or an undelivered message.
 *
 * Reconnecting stays a quiet `Activity` line. Every failed kind is a bordered card with the reason and
 * the actions under one left edge; red is limited to the icon.
 */
export function RunAlertActivity({
    kind,
    id,
    attempt,
    maxAttempts,
    message,
    undeliveredMessage,
    copyDetails,
}: RunAlertActivityProps): JSX.Element {
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

    // A stopped run gets a bordered card, not a tinted banner: red only on the icon, and the reason and
    // the actions share the title's left edge.
    return (
        <div
            className="max-w-4/5 rounded border border-border-secondary bg-surface-primary px-3 py-2.5 flex flex-col gap-1.5"
            data-attr="run-alert-card"
        >
            <div className="flex items-center gap-2 font-semibold">
                <IconWarning className="size-4 shrink-0 text-danger" />
                <span>{TITLES[kind]}</span>
            </div>
            <div className="pl-6 flex flex-col gap-1 text-secondary">
                {message ? <MarkdownMessage content={message} id={`${activityId}-message`} /> : null}
                {undeliveredMessage && kind !== 'message_undelivered' ? (
                    <div>Your last message was not delivered.</div>
                ) : null}
            </div>
            {copyDetails && (
                <div className="pl-6 flex items-center">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={() => void copyToClipboard(copyDetails, 'run details')}
                        data-attr="run-error-copy-details"
                    >
                        Copy details
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
