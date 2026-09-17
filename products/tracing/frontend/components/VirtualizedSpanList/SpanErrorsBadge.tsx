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
// span's own failure, and its noun stays vaguer.
const TIERS: Record<SpanErrorTier, { iconClass: string; noun: string; where: string }> = {
    span: { iconClass: 'text-danger', noun: 'error', where: 'in this span' },
    trace: { iconClass: 'text-danger', noun: 'error', where: 'in this trace' },
    session: { iconClass: 'text-warning', noun: 'error occurrence', where: 'in this session' },
}

export function SpanErrorsBadge({ tier, errorCount, onClick }: SpanErrorsBadgeProps): JSX.Element {
    const { iconClass, noun, where } = TIERS[tier]
    const label = `${pluralize(errorCount, noun)} ${where}`

    return (
        <LemonButton
            size="xsmall"
            icon={<IconWarning className={iconClass} />}
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
