import { LemonButton } from '@posthog/lemon-ui'

import type { MetricNotice } from './metricCardSpec'

/** Stands in for a metric card whenever there is no number to show, so the grid never renders an
 * empty bordered box. Matches the metric card's own shell. */
export function MetricNoticeCard({ title, message, action }: Omit<MetricNotice, 'kind' | 'key'>): JSX.Element {
    return (
        <div className="relative flex h-full flex-col justify-between gap-2 rounded border bg-surface-primary p-3">
            <span className="font-semibold">{title}</span>
            <span className="text-secondary text-sm">{message}</span>
            {action && (
                <div>
                    <LemonButton size="small" type="secondary" onClick={action.onClick} data-attr={action.dataAttr}>
                        {action.label}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
