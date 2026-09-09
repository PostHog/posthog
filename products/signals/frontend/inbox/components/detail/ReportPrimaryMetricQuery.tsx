import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricValue,
    reportMetricAggregate,
    reportMetricChartType,
    reportMetricSeriesPoints,
} from '../../utils/reportMetrics'
import { comparisonMetaSegments, measuredMetaSegments, ReportMetricMetaLine } from './ReportMetricMetaLine'
import { ReportObservationCard } from './ReportObservationCard'
import { ReportObservationChart } from './ReportObservationChart'
import { ReportObservationValue } from './ReportObservationValue'

export function ReportPrimaryMetricQuery({
    reportId,
    metric,
    aggregateQuery,
    seriesQuery,
}: {
    reportId: string
    metric: ReportMetricApi
    aggregateQuery: TrendsQuery
    seriesQuery: InsightVizNode<TrendsQuery>
}): JSX.Element {
    const collectionId = `report-metrics-${reportId}`
    const aggregateProps: DataNodeLogicProps = {
        key: `ReportMetricAggregate.${reportId}.${metric.metric_id}`,
        query: aggregateQuery,
        dataNodeCollectionId: collectionId,
        autoLoad: true,
    }
    const seriesProps: DataNodeLogicProps = {
        key: `ReportMetricSeries.${reportId}.${metric.metric_id}`,
        query: seriesQuery.source,
        dataNodeCollectionId: collectionId,
        autoLoad: true,
    }
    const { response, responseError, responseLoading } = useValues(dataNodeLogic(aggregateProps))
    const {
        response: seriesResponse,
        responseError: seriesError,
        responseLoading: seriesLoading,
    } = useValues(dataNodeLogic(seriesProps))

    const aggregate = reportMetricAggregate(response)
    const hasAggregate = formatReportMetricValue(metric, aggregate) !== null
    const snapshot = formatReportMetricValue(metric, metric.value)
    const responseResolved = response !== null && response !== undefined
    const seriesResolved = seriesResponse !== null && seriesResponse !== undefined
    const points = seriesResolved ? reportMetricSeriesPoints(seriesResponse) : null

    const liveMeta = <ReportMetricMetaLine segments={comparisonMetaSegments(metric, aggregate)} />
    const snapshotMeta = snapshot ? (
        <ReportMetricMetaLine
            segments={[...comparisonMetaSegments(metric, metric.value), ...measuredMetaSegments(metric)]}
        />
    ) : null

    return (
        <ReportObservationCard metric={metric}>
            <div className="flex min-h-8 flex-col gap-1">
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
            {seriesLoading && !seriesResolved ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : seriesError ? (
                <p className="m-0 text-xs text-tertiary">Couldn't load the trend. Refresh the page to try again.</p>
            ) : points ? (
                <ReportObservationChart
                    metric={metric}
                    points={points}
                    type={reportMetricChartType(metric)}
                    interval={seriesQuery.source.interval}
                />
            ) : null}
        </ReportObservationCard>
    )
}
