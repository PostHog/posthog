import { IconCheck, IconCollapse, IconWarning, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ThreadItem } from '../types/streamTypes'
import { Activity } from './ActivityPrimitives'
import type { ActivityStatus } from './ActivityPrimitives'

/** Inline `_posthog/status` item — a spinner while compacting, a generic status line otherwise. */
export function StatusItem({ item }: { item: ThreadItem }): JSX.Element {
    const isCompacting = item.status === 'compacting' && !item.isComplete
    return (
        <div className="flex items-center justify-center gap-2 py-1 text-xs text-muted">
            {isCompacting ? (
                <>
                    <Spinner className="size-3" />
                    <span>Compacting conversation history…</span>
                </>
            ) : (
                <span>Status: {item.status}</span>
            )}
        </div>
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
