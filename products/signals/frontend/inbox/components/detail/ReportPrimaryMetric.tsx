import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    asReportMetricAggregateQuery,
    asReportMetricBarQuery,
    formatReportMetricValue,
} from '../../utils/reportMetrics'
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

        return (
            <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3" data-attr="report-primary-metric">
                <h2 className="m-0 text-sm font-semibold text-primary">{metric.title}</h2>
                <div className="text-2xl font-semibold tabular-nums">{snapshot ?? 'Not available'}</div>
                {snapshot && metric.value_at ? (
                    <span className="text-xs text-tertiary">
                        Measured <TZLabel time={metric.value_at} />
                    </span>
                ) : null}
            </LemonCard>
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
