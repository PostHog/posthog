import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

export type RunStatus = 'pending' | 'processing' | 'completed' | 'failed'

const STATUS_CONFIG: Record<RunStatus, { label: string; type: LemonTagType }> = {
    pending: { label: 'Pending', type: 'default' },
    processing: { label: 'Processing', type: 'highlight' },
    completed: { label: 'Completed', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
}

interface RunStatusBadgeProps {
    status: string
    hasUnapprovedChanges?: boolean
    approved?: boolean
}

export function RunStatusBadge({ status, hasUnapprovedChanges, approved }: RunStatusBadgeProps): JSX.Element {
    // When the pipeline is done, show the review-relevant status
    if (status === 'completed') {
        if (hasUnapprovedChanges) {
            return <LemonTag type="warning">Needs review</LemonTag>
        }
        if (approved) {
            return <LemonTag type="success">Approved</LemonTag>
        }
        return <LemonTag type="success">Clean</LemonTag>
    }

    const config = STATUS_CONFIG[status as RunStatus] || { label: status, type: 'default' as LemonTagType }
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
