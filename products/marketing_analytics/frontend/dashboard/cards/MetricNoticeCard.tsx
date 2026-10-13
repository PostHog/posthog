import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import type { MetricNotice } from './metricCardSpec'

export type MetricNoticeCardProps = Omit<MetricNotice, 'kind' | 'key'>

/** Stands in for a metric card whenever there is no number to show, so the grid never renders an
 * empty bordered box. Matches the metric card's own shell. */
export function MetricNoticeCard({ title, message, action, value }: MetricNoticeCardProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col gap-1 p-3">
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
        </LemonCard>
    )
}
