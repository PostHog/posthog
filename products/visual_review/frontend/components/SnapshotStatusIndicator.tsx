import { IconCheck } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

interface SnapshotStatusIndicatorProps {
    result: string
    reviewState: string
    classificationReason?: string
    /** 'small' = filmstrip dot, 'medium' = table inline, 'full' = detail view */
    size?: 'small' | 'medium' | 'full'
    /** @deprecated Use size='small' instead */
    compact?: boolean
}

const RESULT_STYLES: Record<string, { dot: string; text: string; label: string; bg: string }> = {
    changed: { dot: 'bg-warning', text: 'text-warning-dark', label: 'Changed', bg: 'bg-warning-highlight' },
    new: { dot: 'bg-success', text: 'text-success', label: 'New', bg: 'bg-success-highlight' },
    removed: { dot: 'bg-danger', text: 'text-danger', label: 'Removed', bg: 'bg-danger-highlight' },
    unchanged: { dot: 'bg-muted', text: 'text-muted', label: 'Unchanged', bg: 'bg-fill-secondary' },
}

function reviewBadge(reviewState: string): { text: string; className: string } | null {
    if (reviewState === 'approved') {
        return { text: 'Approved', className: 'text-success' }
    }
    if (reviewState === 'tolerated') {
        return { text: 'Tolerated', className: 'text-muted' }
    }
    return null
}

function resultLabel(result: string, classificationReason?: string): string {
    if (result === 'unchanged' && classificationReason === 'tolerated_hash') {
        return 'Auto-tolerated'
    }
    return RESULT_STYLES[result]?.label || result
}

export function SnapshotStatusIndicator({
    result,
    reviewState,
    classificationReason,
    size,
    compact = false,
}: SnapshotStatusIndicatorProps): JSX.Element {
    const effectiveSize = size ?? (compact ? 'small' : 'full')
    const styles = RESULT_STYLES[result] || RESULT_STYLES.unchanged
    const review = reviewBadge(reviewState)
    const label = resultLabel(result, classificationReason)
    const hasBaseline = result !== 'new'

    if (effectiveSize === 'small') {
        const tooltip = [label, review?.text].filter(Boolean).join(' · ')
        return (
            <Tooltip title={tooltip}>
                <span className="flex items-center gap-0.5">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
                    {review && (
                        <span className={`text-[9px] leading-none shrink-0 ${review.className}`}>
                            {reviewState === 'approved' ? '✓' : '~'}
                        </span>
                    )}
                </span>
            </Tooltip>
        )
    }

    if (effectiveSize === 'medium') {
        return (
            <span className="flex items-center gap-1.5">
                <span className="flex items-center gap-1">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
                    <span className={`text-xs font-medium ${styles.text}`}>{label}</span>
                </span>
                {review && (
                    <span className={`text-xs ${review.className}`}>
                        {reviewState === 'approved' && <IconCheck className="w-3.5 h-3.5 inline" />}
                        {reviewState === 'tolerated' && '~'}
                    </span>
                )}
            </span>
        )
    }

    return (
        <span className="flex items-center gap-2">
            {/* Transition pill */}
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs ${styles.bg}`}>
                {hasBaseline && <span className="text-muted">before</span>}
                <span className={styles.text}>→ {label.toLowerCase()}</span>
            </span>

            {/* Review badge */}
            {review && (
                <span className={`flex items-center gap-1 text-sm font-medium ${review.className}`}>
                    {reviewState === 'approved' && <IconCheck className="w-3.5 h-3.5" />}
                    {review.text}
                </span>
            )}
        </span>
    )
}
