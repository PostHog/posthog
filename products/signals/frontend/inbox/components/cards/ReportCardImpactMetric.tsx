import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricParts,
    formatReportMetricValue,
    reportMetricChartType,
    reportMetricRowParts,
    selectReportCardImpactMetric,
} from '../../utils/reportMetrics'
import { ReportCardSparkline } from './ReportCardSparkline'

/**
 * The row's headline impact: the trailing buckets as a bar or line strip, then the figure over its unit word.
 * What it measures, when, and the exact value of a shortened figure live in the tooltip.
 *
 * The two columns are fixed so figures and strips line up down a list of rows. The strip column keeps
 * its width on a row with no series, so a figure never slides left out of the column.
 */
export function ReportCardImpactMetric({ metrics }: { metrics?: ReportMetricApi[] }): JSX.Element | null {
    const metric = selectReportCardImpactMetric(metrics)
    const parts = metric ? reportMetricRowParts(metric, metric.value) : null

    if (!metric || !parts) {
        return null
    }

    const series = metric.series?.filter((point) => Number.isFinite(point)) ?? []
    const shortened = formatReportMetricParts(metric, metric.value)?.value !== parts.value

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-0.5">
                    <span>{metric.title}</span>
                    {shortened ? (
                        <span className="font-mono text-xs tabular-nums">
                            {formatReportMetricValue(metric, metric.value)}
                        </span>
                    ) : null}
                    {metric.value_at ? (
                        <span className="text-xs">
                            Measured <TZLabel time={metric.value_at} showPopover={false} timestampStyle="absolute" />
                        </span>
                    ) : null}
                </div>
            }
        >
            <div
                className="grid shrink-0 grid-cols-[5rem_4rem] items-center gap-3"
                data-attr="report-card-impact-metric"
            >
                <div className="flex items-center justify-end">
                    {series.length > 1 ? (
                        <ReportCardSparkline values={series} type={reportMetricChartType(metric)} />
                    ) : null}
                </div>
                <div className="flex min-w-0 flex-col items-center gap-0.5 text-center">
                    <span className="max-w-full truncate font-mono text-sm font-semibold leading-tight tabular-nums text-primary">
                        {parts.value}
                    </span>
                    {parts.unit ? (
                        <span className="max-w-full truncate font-mono text-[10px] leading-tight text-secondary">
                            {parts.unit}
                        </span>
                    ) : null}
                </div>
            </div>
        </Tooltip>
    )
}
