import { ReactNode } from 'react'

import { LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { WorkflowState } from '../lib/runHealth'

// The classes are literal token utilities, not built strings, so Tailwind keeps them.
export const STATE_META: Record<
    WorkflowState,
    { word: string; tag: LemonTagType; borderClass: string; dotClass: string; wordClass: string }
> = {
    healthy: {
        word: 'Healthy',
        tag: 'success',
        borderClass: 'border-l-success',
        dotClass: 'bg-success',
        wordClass: 'text-success',
    },
    degraded: {
        word: 'Degraded',
        tag: 'warning',
        borderClass: 'border-l-warning',
        dotClass: 'bg-warning',
        wordClass: 'text-warning',
    },
    failing: {
        word: 'Failing',
        tag: 'danger',
        borderClass: 'border-l-danger',
        dotClass: 'bg-danger',
        wordClass: 'text-danger',
    },
    unknown: {
        word: 'No data',
        tag: 'muted',
        borderClass: 'border-l-muted',
        dotClass: 'bg-muted',
        wordClass: 'text-muted',
    },
}

export function HealthKpi({
    label,
    value,
    danger,
}: {
    label: string
    value: ReactNode
    danger?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-tertiary">{label}</span>
            <span className={cn('text-lg font-semibold leading-6 tabular-nums', danger && 'text-danger')}>{value}</span>
        </div>
    )
}
