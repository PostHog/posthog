import { ReactNode } from 'react'

import { LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { WorkflowState } from '../lib/runHealth'

// Verdict word + accent color (a real PostHog CSS var, so it tracks the theme) + tag type per state,
// matching the run tables' StatusDot palette: green healthy, amber degraded, red failing. Shared by the
// single-workflow header and the all-workflows (fleet) header so both read identically.
export const STATE_META: Record<WorkflowState, { word: string; color: string; tag: LemonTagType }> = {
    healthy: { word: 'Healthy', color: 'var(--success)', tag: 'success' },
    degraded: { word: 'Degraded', color: 'var(--warning)', tag: 'warning' },
    failing: { word: 'Failing', color: 'var(--danger)', tag: 'danger' },
    unknown: { word: 'No data', color: 'var(--muted)', tag: 'muted' },
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
