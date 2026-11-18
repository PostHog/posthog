import type { ReactNode } from 'react'

import { LemonCard } from '@posthog/lemon-ui'

export interface RequestUsageSummaryCardProps {
    label: string
    value: number | string
    footer?: ReactNode
}

export function RequestUsageSummaryCard({ label, value, footer }: RequestUsageSummaryCardProps): JSX.Element {
    return (
        <LemonCard className="p-4">
            <div className="text-secondary">{label}</div>
            <div className="text-2xl font-semibold tabular-nums truncate">
                {typeof value === 'number' ? value.toLocaleString() : value}
            </div>
            {footer && <div className="text-secondary tabular-nums">{footer}</div>}
        </LemonCard>
    )
}
