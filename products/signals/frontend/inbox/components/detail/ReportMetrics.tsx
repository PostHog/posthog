import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { asReportMetricAggregateQuery } from '../../utils/reportMetrics'
import { ReportPrimaryMetric } from './ReportPrimaryMetric'
import { ReportSupportingMetric } from './ReportSupportingMetric'
import { ReportSupportingMetricQuery } from './ReportSupportingMetricQuery'

export function ReportMetrics({
    reportId,
    metrics,
}: {
    reportId: string
    metrics?: ReportMetricApi[]
}): JSX.Element | null {
    if (!metrics?.length) {
        return null
    }

    const primaryMetric = metrics.find((metric) => metric.role === 'primary')
    const supportingMetrics = metrics.filter((metric) => metric.role !== 'primary')

    if (!primaryMetric && supportingMetrics.length === 0) {
        return null
    }

    return (
        <section className="@container/report-metrics flex flex-col gap-4" aria-label="Report metrics">
            {primaryMetric ? <ReportPrimaryMetric reportId={reportId} metric={primaryMetric} /> : null}
            {supportingMetrics.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <h2 className="m-0 text-sm font-semibold text-primary">Impact</h2>
                    <div className="grid grid-cols-1 gap-2 @min-[24rem]/report-metrics:grid-cols-2 @min-[48rem]/report-metrics:grid-cols-3">
                        {supportingMetrics.map((metric) => {
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
            ) : null}
        </section>
    )
}
