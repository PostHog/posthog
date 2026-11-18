import clsx from 'clsx'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { asReportMetricAggregateQuery } from '../../utils/reportMetrics'
import { ReportSupportingMetric } from './ReportSupportingMetric'
import { ReportSupportingMetricQuery } from './ReportSupportingMetricQuery'

// One tile per column up to four, so a report with two or three tiles does not leave an empty slot.
// Tailwind needs the full class strings written out, so each count is listed explicitly.
const IMPACT_GRID: Record<number, string> = {
    1: 'grid-cols-1',
    2: 'grid-cols-1 @min-[24rem]/report-impact:grid-cols-2',
    3: 'grid-cols-1 @min-[24rem]/report-impact:grid-cols-2 @min-[40rem]/report-impact:grid-cols-3',
    4: 'grid-cols-1 @min-[24rem]/report-impact:grid-cols-2 @min-[48rem]/report-impact:grid-cols-4',
}

/** The supporting metrics as a grid of tiles. Callers own the heading, so it can sit under the summary's Impact section. */
export function ReportImpactMetrics({
    reportId,
    metrics,
}: {
    reportId: string
    metrics: ReportMetricApi[]
}): JSX.Element | null {
    if (metrics.length === 0) {
        return null
    }

    return (
        <div className="@container/report-impact" data-attr="report-impact-metrics">
            <div className={clsx('grid gap-2.5', IMPACT_GRID[metrics.length] ?? IMPACT_GRID[3])}>
                {metrics.map((metric) => {
                    const query = asReportMetricAggregateQuery(metric.query)

                    return query ? (
                        <ReportSupportingMetricQuery
                            key={metric.metric_id}
                            reportId={reportId}
                            metric={metric}
                            query={query.source}
                        />
                    ) : (
                        <ReportSupportingMetric key={metric.metric_id} metric={metric} />
                    )
                })}
            </div>
        </div>
    )
}
