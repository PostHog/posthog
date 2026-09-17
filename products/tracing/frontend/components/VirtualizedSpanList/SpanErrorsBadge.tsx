import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { SpanErrorTier } from '../../spanErrorsLogic'

export interface SpanErrorsBadgeProps {
    tier: SpanErrorTier
    errorCount: number
    onClick: () => void
}

// A session count is only co-occurring evidence, so it reads as a warning rather than as this
// span's own failure.
const TIER_ICON_CLASS: Record<SpanErrorTier, string> = {
    span: 'text-danger',
    trace: 'text-danger',
    session: 'text-warning',
}

function tierLabel(tier: SpanErrorTier, errorCount: number): string {
    if (tier === 'span') {
        return `${pluralize(errorCount, 'error')} in this span`
    }
    if (tier === 'trace') {
        return `${pluralize(errorCount, 'error')} in this trace`
    }
    return `${pluralize(errorCount, 'error occurrence')} in this session`
}

export function SpanErrorsBadge({ tier, errorCount, onClick }: SpanErrorsBadgeProps): JSX.Element {
    const label = tierLabel(tier, errorCount)

    return (
        <LemonButton
            size="xsmall"
            icon={<IconWarning className={TIER_ICON_CLASS[tier]} />}
            tooltip={`${label}. Click to see them.`}
            aria-label={label}
            data-attr="tracing-row-errors"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
                e.stopPropagation()
                onClick()
            }}
        />
    )
}
