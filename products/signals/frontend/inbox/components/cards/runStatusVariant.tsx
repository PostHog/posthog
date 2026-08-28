import clsx from 'clsx'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { SignalReportStatus, SignalScoutRunStatus } from '../../types'

export type RunVariant = 'queued' | 'live' | 'completed' | 'failed'

export function resolveRunVariant(
    status: SignalScoutRunStatus | SignalReportStatus | TaskRunStatus | null | undefined
): RunVariant {
    switch (status) {
        case 'in_progress':
        case 'pending_input':
            return 'live'
        case 'completed':
        case 'ready':
        case 'resolved':
        case 'deleted':
        case 'suppressed':
            return 'completed'
        case 'failed':
        case 'cancelled':
            return 'failed'
        default:
            return 'queued'
    }
}

export function isRunLive(status: SignalScoutRunStatus | null): boolean {
    const variant = resolveRunVariant(status)
    return variant === 'live' || variant === 'queued'
}

export interface VariantMeta {
    label: string
    dotClass: string
    ariaLabel: string
}

export const VARIANT_META: Record<RunVariant, VariantMeta> = {
    queued: {
        label: 'Queued',
        dotClass: 'bg-muted',
        ariaLabel: 'Queued',
    },
    live: {
        label: 'Running',
        dotClass: 'bg-accent animate-pulse',
        ariaLabel: 'In progress',
    },
    completed: {
        label: 'Completed',
        dotClass: 'bg-success',
        ariaLabel: 'Completed',
    },
    failed: {
        label: 'Failed',
        dotClass: 'bg-danger',
        ariaLabel: 'Failed',
    },
}

export function RunStatusIndicator({
    variant,
    showLabel = true,
    className,
}: {
    variant: RunVariant
    showLabel?: boolean
    className?: string
}): JSX.Element {
    const meta = VARIANT_META[variant]

    return (
        <span
            className={clsx('inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-secondary', className)}
        >
            <span
                className={clsx('block size-2 shrink-0 rounded-full', meta.dotClass)}
                role={showLabel ? undefined : 'img'}
                aria-label={showLabel ? undefined : meta.ariaLabel}
                aria-hidden={showLabel || undefined}
            />
            {showLabel ? meta.label : null}
        </span>
    )
}
