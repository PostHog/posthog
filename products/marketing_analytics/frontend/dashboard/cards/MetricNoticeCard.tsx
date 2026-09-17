import { LemonButton } from '@posthog/lemon-ui'

import type { MetricNotice } from './metricCardSpec'

export interface MetricNoticeCardProps extends Omit<MetricNotice, 'kind' | 'key'> {
    /** Stands in the value's place, for a metric that exists but cannot be computed here. */
    value?: string
}

/** Stands in for a metric card whenever there is no number to show, so the grid never renders an
 * empty bordered box. Matches the metric card's own shell. */
export function MetricNoticeCard({ title, message, action, value }: MetricNoticeCardProps): JSX.Element {
    return (
        <div className="relative flex h-full flex-col gap-1 rounded border bg-surface-primary p-3">
            <span className="text-xs font-medium text-secondary truncate">{title}</span>
            {value && <span className="text-2xl font-semibold text-muted tabular-nums">{value}</span>}
            <span className="text-secondary text-xs">{message}</span>
            {action && (
                <div className="mt-auto pt-1">
                    <LemonButton size="small" type="secondary" onClick={action.onClick} data-attr={action.dataAttr}>
                        {action.label}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
