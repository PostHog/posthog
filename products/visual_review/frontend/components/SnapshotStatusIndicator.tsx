import { IconCheck } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

interface SnapshotStatusIndicatorProps {
    result: string
    reviewState: string
    classificationReason?: string
    compact?: boolean
}

const RESULT_COLORS: Record<string, { dot: string; text: string }> = {
    changed: { dot: 'bg-warning', text: 'text-warning-dark' },
    new: { dot: 'bg-primary', text: 'text-primary-dark' },
    removed: { dot: 'bg-danger', text: 'text-danger' },
    unchanged: { dot: 'bg-muted', text: 'text-muted' },
}

function transitionLabel(result: string, classificationReason?: string): string {
    if (result === 'new') {
        return '→ new'
    }
    if (result === 'removed') {
        return '(baseline) → removed'
    }
    if (result === 'unchanged' && classificationReason === 'tolerated_hash') {
        return '(baseline) → auto-tolerated'
    }
    if (result === 'changed') {
        return '(baseline) → changed'
    }
    return ''
}

function reviewLabel(reviewState: string): { text: string; className: string } | null {
    if (reviewState === 'approved') {
        return { text: 'Approved', className: 'text-success' }
    }
    if (reviewState === 'tolerated') {
        return { text: 'Tolerated', className: 'text-muted' }
    }
    return null
}

export function SnapshotStatusIndicator({
    result,
    reviewState,
    classificationReason,
    compact = false,
}: SnapshotStatusIndicatorProps): JSX.Element {
    const colors = RESULT_COLORS[result] || RESULT_COLORS.unchanged
    const review = reviewLabel(reviewState)
    const transition = transitionLabel(result, classificationReason)

    if (compact) {
        const tooltip = [transition, review?.text].filter(Boolean).join(' · ') || result
        return (
            <Tooltip title={tooltip}>
                <span className="flex items-center gap-0.5">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                    {review && (
                        <span className={`text-[9px] leading-none shrink-0 ${review.className}`}>
                            {reviewState === 'approved' ? '✓' : '~'}
                        </span>
                    )}
                </span>
            </Tooltip>
        )
    }

    return (
        <span className="flex items-center gap-2">
            {transition && <span className={`text-xs font-mono ${colors.text}`}>{transition}</span>}
            {review && (
                <span className={`flex items-center gap-1 text-sm font-medium ${review.className}`}>
                    {reviewState === 'approved' && <IconCheck className="w-4 h-4" />}
                    {review.text}
                </span>
            )}
        </span>
    )
}
