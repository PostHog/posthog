import { IconCheck } from '@posthog/icons'
import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

export type SnapshotResult = 'unchanged' | 'changed' | 'new' | 'removed'

const RESULT_CONFIG: Record<SnapshotResult, { label: string; type: LemonTagType }> = {
    unchanged: { label: 'Unchanged', type: 'muted' },
    changed: { label: 'Changed', type: 'warning' },
    new: { label: 'New', type: 'highlight' },
    removed: { label: 'Removed', type: 'danger' },
}

interface SnapshotResultBadgeProps {
    result: string
    approvedAt?: string | null
}

export function SnapshotResultBadge({ result, approvedAt }: SnapshotResultBadgeProps): JSX.Element {
    const config = RESULT_CONFIG[result as SnapshotResult] || { label: result, type: 'default' as LemonTagType }
    const isApproved = !!approvedAt

    return (
        <span className="inline-flex items-center gap-1">
            <LemonTag type={isApproved ? 'success' : config.type}>{config.label}</LemonTag>
            {isApproved && (
                <Tooltip title="Approved">
                    <IconCheck className="text-success w-4 h-4" />
                </Tooltip>
            )}
        </span>
    )
}
