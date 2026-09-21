import { IconCheck, IconCircleDashed, IconCollapse, IconWarning, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ThreadItem } from '../types/streamTypes'
import { Activity } from './ActivityPrimitives'
import type { ActivityStatus } from './ActivityPrimitives'

/** Statuses that run for a while and get a spinner with their own label, keyed by wire status. */
const IN_PROGRESS_STATUS_LABELS: Record<string, string> = {
    compacting: 'Compacting conversation history…',
    clearing: 'Clearing conversation…',
}

function StatusLine({ icon, children }: { icon?: JSX.Element; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-center gap-2 py-1 text-xs text-muted">
            {icon}
            <span>{children}</span>
        </div>
    )
}

/** Inline `_posthog/status` item — a spinner while an operation runs, a status line otherwise. */
export function StatusItem({ item }: { item: ThreadItem }): JSX.Element {
    const inProgressLabel = item.isComplete ? undefined : IN_PROGRESS_STATUS_LABELS[item.status ?? '']
    if (inProgressLabel) {
        return <StatusLine icon={<Spinner className="size-3" />}>{inProgressLabel}</StatusLine>
    }
    // A failed clear leaves the agent session closed, so the way forward is a new run, not a retry.
    if (item.status === 'clearing_failed') {
        const reason = item.errorMessage
            ? `Couldn't clear the conversation: ${item.errorMessage}`
            : "Couldn't clear the conversation"
        return <StatusLine icon={<IconX className="size-3" />}>{reason}. Start a new run to keep going.</StatusLine>
    }
    return <StatusLine>Status: {item.status}</StatusLine>
}

/** Inline `_posthog/conversation_cleared` item — the `/clear` boundary card. */
export function ConversationClearedItem({ item }: { item: ThreadItem }): JSX.Element {
    return (
        <Activity
            id={item.id}
            title="Conversation cleared"
            subtitle="Earlier messages are no longer in the agent's context"
            status="completed"
            icon={<IconCircleDashed className="size-4" />}
            animate={false}
            showCompletionIcon={false}
        />
    )
}

/** Inline `_posthog/compact_boundary` item — the post-compaction card. */
export function CompactBoundaryItem({ item }: { item: ThreadItem }): JSX.Element {
    const parts = [
        item.trigger ? `(${item.trigger})` : null,
        typeof item.preTokens === 'number' ? `~${humanFriendlyNumber(item.preTokens)} tokens summarized` : null,
    ].filter(Boolean)
    const subtitle = parts.length > 0 ? parts.join(' · ') : undefined
    return (
        <Activity
            id={item.id}
            title="Conversation compacted"
            subtitle={subtitle}
            status="completed"
            icon={<IconCollapse className="size-4" />}
            animate={false}
            showCompletionIcon={false}
        />
    )
}

/** Inline `_posthog/task_notification` item — a status card for a completed/failed/stopped task. */
export function TaskNotificationItem({ item }: { item: ThreadItem }): JSX.Element {
    const activityStatus: ActivityStatus = item.status === 'completed' ? 'completed' : 'failed'
    const icon =
        item.status === 'completed' ? (
            <IconCheck className="size-4" />
        ) : item.status === 'failed' ? (
            <IconX className="size-4" />
        ) : (
            <IconWarning className="size-4" />
        )
    return (
        <Activity
            id={item.id}
            title={item.summary || `Task ${item.status}`}
            status={activityStatus}
            icon={icon}
            animate={false}
            showCompletionIcon={false}
        />
    )
}
