import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue } from '../../utils/reportMetrics'

export function selectReportCardImpactMetric(metrics?: ReportMetricApi[]): ReportMetricApi | null {
    if (!metrics?.length) {
        return null
    }

    const hasSnapshot = (metric: ReportMetricApi): boolean =>
        metric.value !== null && Number.isFinite(metric.value) && formatReportMetricValue(metric, metric.value) !== null

    return (
        metrics.find((metric) => metric.kind === 'affected_users' && hasSnapshot(metric)) ??
        metrics.find((metric) => metric.role === 'primary' && hasSnapshot(metric)) ??
        null
    )
}

export function ReportCardImpactMetric({ metrics }: { metrics?: ReportMetricApi[] }): JSX.Element | null {
    const metric = selectReportCardImpactMetric(metrics)
    const value = metric ? formatReportMetricValue(metric, metric.value) : null

    if (!metric || !value) {
        return null
    }

    const content = (
        <div
            className="flex min-w-0 items-baseline gap-1.5 text-xs text-secondary"
            data-attr="report-card-impact-metric"
        >
            <span className="shrink-0 font-semibold tabular-nums text-primary">{value}</span>
            <span className="truncate">{metric.title}</span>
        </div>
    )

    return metric.value_at ? (
        <Tooltip
            title={
                <span>
                    Measured <TZLabel time={metric.value_at} showPopover={false} timestampStyle="absolute" />
                </span>
            }
        >
            {content}
        </Tooltip>
    ) : (
        content
    )
}
