import { useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue, reportMetricAggregate, reportMetricWindowLabel } from '../../utils/reportMetrics'
import { comparisonMetaSegments, measuredMetaSegments, ReportMetricMetaLine } from './ReportMetricMetaLine'
import { ReportObservationCard } from './ReportObservationCard'
import { ReportObservationValue } from './ReportObservationValue'

export function ReportPrimaryMetricQuery({
    reportId,
    metric,
    aggregateQuery,
    barQuery,
}: {
    reportId: string
    metric: ReportMetricApi
    aggregateQuery: TrendsQuery
    barQuery: InsightVizNode
}): JSX.Element {
    const metricKey = `report-metric-${reportId}-${metric.metric_id}`
    const insightProps: InsightLogicProps<InsightVizNode> = {
        dashboardItemId: `new-AdHoc.${metricKey}`,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        query: barQuery,
    }
    const dataNodeProps: DataNodeLogicProps = {
        key: `ReportMetricAggregate.${reportId}.${metric.metric_id}`,
        query: aggregateQuery,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        autoLoad: true,
    }
    const { response, responseError, responseLoading } = useValues(dataNodeLogic(dataNodeProps))

    const aggregate = reportMetricAggregate(response)
    const hasAggregate = formatReportMetricValue(metric, aggregate) !== null
    const snapshot = formatReportMetricValue(metric, metric.value)
    const responseResolved = response !== null && response !== undefined
    const windowLabel = reportMetricWindowLabel(metric.query) ?? 'Current window'

    const liveMeta = (
        <ReportMetricMetaLine
            segments={[
                ...comparisonMetaSegments(metric, aggregate),
                { key: 'window', node: <span>{windowLabel}</span> },
            ]}
        />
    )
    const snapshotMeta = snapshot ? (
        <ReportMetricMetaLine
            segments={[...comparisonMetaSegments(metric, metric.value), ...measuredMetaSegments(metric)]}
        />
    ) : null

    return (
        <ReportObservationCard metric={metric}>
            <div className="flex min-h-12 flex-col gap-1.5">
                {responseLoading && !responseResolved ? (
                    <div className="flex items-center gap-2 text-xs text-tertiary">
                        <Spinner className="text-lg" />
                        <span>Loading current value</span>
                    </div>
                ) : responseError ? (
                    <>
                        {snapshot ? <ReportObservationValue metric={metric} value={metric.value} /> : null}
                        <p className="m-0 text-xs text-tertiary">
                            Couldn't refresh this metric.
                            {snapshot ? ' Showing the latest saved value.' : null} Refresh the page to try again.
                        </p>
                        {snapshotMeta}
                    </>
                ) : hasAggregate ? (
                    <>
                        <ReportObservationValue metric={metric} value={aggregate} />
                        {liveMeta}
                    </>
                ) : snapshot ? (
                    <>
                        <ReportObservationValue metric={metric} value={metric.value} />
                        <p className="m-0 text-xs text-tertiary">
                            No value for this window. Showing the latest saved value.
                        </p>
                        {snapshotMeta}
                    </>
                ) : (
                    <span className="text-xs text-tertiary">No value for this window.</span>
                )}
            </div>
            <div className="flex h-28 min-w-0 flex-col overflow-hidden">
                <Query query={barQuery} uniqueKey={metricKey} context={{ insightProps }} readOnly embedded />
            </div>
        </ReportObservationCard>
    )
}
