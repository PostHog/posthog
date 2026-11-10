import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { BroadcastRunStatus, BroadcastStatus } from './broadcastsLogic'

const STATUS_CONFIG: Record<
    Exclude<BroadcastStatus | BroadcastRunStatus, 'unknown'>,
    { label: string; type: LemonTagType }
> = {
    draft: { label: 'Draft', type: 'default' },
    scheduled: { label: 'Scheduled', type: 'warning' },
    sending: { label: 'Sending', type: 'completion' },
    sent: { label: 'Sent', type: 'success' },
    partially_failed: { label: 'Partly failed', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
    cancelled: { label: 'Cancelled', type: 'muted' },
    archived: { label: 'Archived', type: 'muted' },
}

export function BroadcastStatusTag({ status }: { status: BroadcastStatus | BroadcastRunStatus }): JSX.Element {
    if (status === 'unknown') {
        return <span className="text-muted">…</span>
    }
    const config = STATUS_CONFIG[status]
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
