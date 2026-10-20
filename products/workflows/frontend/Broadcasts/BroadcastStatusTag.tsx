import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { BroadcastStatus } from './broadcastsLogic'

const STATUS_CONFIG: Record<Exclude<BroadcastStatus, 'unknown'>, { label: string; type: LemonTagType }> = {
    draft: { label: 'Draft', type: 'default' },
    scheduled: { label: 'Scheduled', type: 'warning' },
    sending: { label: 'Sending', type: 'completion' },
    sent: { label: 'Sent', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    archived: { label: 'Archived', type: 'muted' },
}

export function BroadcastStatusTag({ status }: { status: BroadcastStatus }): JSX.Element {
    if (status === 'unknown') {
        return <span className="text-muted">…</span>
    }
    const config = STATUS_CONFIG[status]
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
