import { ReactNode } from 'react'

import { LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { WorkflowState } from '../lib/runHealth'

// Verdict word + accent color (a real PostHog CSS var, so it tracks the theme) + tag type + the matching
// left-border accent class per state, matching the run tables' StatusDot palette: green healthy, amber
// degraded, red failing. Shared by the single-workflow and all-workflows (fleet) headers so both read
// identically. `borderClass` is a literal token class (not built from a string) so Tailwind keeps it.
export const STATE_META: Record<
    WorkflowState,
    { word: string; color: string; tag: LemonTagType; borderClass: string }
> = {
    healthy: { word: 'Healthy', color: 'var(--success)', tag: 'success', borderClass: 'border-l-success' },
    degraded: { word: 'Degraded', color: 'var(--warning)', tag: 'warning', borderClass: 'border-l-warning' },
    failing: { word: 'Failing', color: 'var(--danger)', tag: 'danger', borderClass: 'border-l-danger' },
    unknown: { word: 'No data', color: 'var(--muted)', tag: 'muted', borderClass: 'border-l-muted' },
}

/** One headline rollup in a verdict strip: small label over a big tabular number. */
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
