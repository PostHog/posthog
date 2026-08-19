import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { InvestigationState } from '../types'

const STATE_TO_TAG: Record<InvestigationState, { type: LemonTagType; label: string }> = {
    worsening: { type: 'danger', label: 'Worsening' },
    recovering: { type: 'success', label: 'Recovering' },
    holding: { type: 'caution', label: 'Holding' },
    measuring: { type: 'highlight', label: 'Measuring' },
    resolved: { type: 'muted', label: 'Resolved' },
    disputed: { type: 'warning', label: 'Disputed' },
    dismissed: { type: 'muted', label: 'Dismissed' },
}

/** State chip for an investigation. Pulses while the engine is still measuring live. */
export function InvestigationStateTag({
    state,
    live,
    className,
}: {
    state: InvestigationState
    live?: boolean
    className?: string
}): JSX.Element {
    const { type, label } = STATE_TO_TAG[state]
    return (
        <LemonTag
            type={type}
            size="small"
            className={cn('font-mono uppercase', live && 'animate-pulse motion-reduce:animate-none', className)}
        >
            {label}
        </LemonTag>
    )
}
