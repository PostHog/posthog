import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    asReportMetricAggregateQuery,
    asReportMetricBarQuery,
    formatReportMetricValue,
} from '../../utils/reportMetrics'
import { comparisonMetaSegments, measuredMetaSegments, ReportMetricMetaLine } from './ReportMetricMetaLine'
import { ReportObservationCard } from './ReportObservationCard'
import { ReportObservationValue } from './ReportObservationValue'
import { ReportPrimaryMetricQuery } from './ReportPrimaryMetricQuery'

export function ReportPrimaryMetric({ reportId, metric }: { reportId: string; metric: ReportMetricApi }): JSX.Element {
    const aggregateQuery = asReportMetricAggregateQuery(metric.query)
    const barQuery = asReportMetricBarQuery(metric.query)

    if (!aggregateQuery || !barQuery) {
        // No query means nothing ran: the list projection omits it during the detail fetch, and access
        // rules can redact it for a viewer. Show the saved snapshot or `Not available`, not a load
        // failure the reader cannot fix by refreshing. A live query that fails is handled downstream in
        // ReportPrimaryMetricQuery.
        const snapshot = formatReportMetricValue(metric, metric.value)
        const segments = snapshot
            ? [...comparisonMetaSegments(metric, metric.value), ...measuredMetaSegments(metric)]
            : []

        return (
            <ReportObservationCard metric={metric}>
                <div className="flex flex-col gap-1.5">
                    <ReportObservationValue metric={metric} value={metric.value} />
                    <ReportMetricMetaLine segments={segments} />
                </div>
            </ReportObservationCard>
        )
    }

    return (
        <ReportPrimaryMetricQuery
            reportId={reportId}
            metric={metric}
            aggregateQuery={aggregateQuery.source}
            barQuery={barQuery}
        />
    )
}
