import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    asReportMetricAggregateQuery,
    asReportMetricSeriesQuery,
    formatReportMetricValue,
    reportMetricAggregate,
    reportMetricChartType,
    reportMetricSeriesPoints,
} from '../../utils/reportMetrics'
import { ReportObservationChart } from './ReportObservationChart'

export function ReportExpectedImpactChart({
    reportId,
    metric,
    query,
    goalGrain,
    version,
}: {
    reportId: string
    metric: ReportMetricApi
    query: NonNullable<ReturnType<typeof asReportMetricSeriesQuery>>['source']
    goalGrain: 'whole_window' | 'per_interval'
    version: string
}): JSX.Element {
    const props: DataNodeLogicProps = {
        key: `ReportMetricSeries.${reportId}.${metric.metric_id}.${version}`,
        query,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        autoLoad: true,
    }
    const { response, responseError, responseLoading } = useValues(dataNodeLogic(props))
    const points = reportMetricSeriesPoints(response)
    const aggregateQuery = asReportMetricAggregateQuery(metric.query)
    const aggregateProps: DataNodeLogicProps = {
        key: `ImpactMeasurementTotal.${reportId}.${metric.metric_id}.${version}`,
        query: aggregateQuery?.source ?? query,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        autoLoad: goalGrain === 'whole_window' && aggregateQuery !== null,
    }
    const { response: aggregateResponse, responseError: aggregateError } = useValues(dataNodeLogic(aggregateProps))
    const aggregate = reportMetricAggregate(aggregateResponse)

    if (responseLoading && !response) {
        return <LemonSkeleton className="h-36 w-full" />
    }
    if (responseError) {
        return <p className="text-tertiary m-0">Couldn't load the chart. Refresh the page to try again.</p>
    }
    if (!points) {
        return <p className="text-tertiary m-0">No chart data for this window. The goal is still a proposal.</p>
    }

    const goal = metric.goal_value
    const max = Math.max(aggregate ?? 0, goal ?? 0, 1)

    return (
        <div className="flex flex-col gap-2">
            <ReportObservationChart
                metric={metric}
                points={points}
                type={reportMetricChartType(metric)}
                interval={query.interval}
                goalValue={goalGrain === 'per_interval' ? (goal ?? undefined) : undefined}
            />
            {goalGrain === 'whole_window' && goal != null && (
                <div className="text-xs text-secondary">
                    <div className="mb-1 flex justify-between">
                        <span>
                            {aggregateError
                                ? 'Current total unavailable'
                                : aggregate == null
                                  ? 'Loading current total'
                                  : `Current window: ${formatReportMetricValue(metric, aggregate)}`}
                        </span>
                        <span>Goal: {formatReportMetricValue(metric, goal)}</span>
                    </div>
                    <div className="relative h-2 rounded bg-fill-highlight-50" aria-hidden>
                        {aggregate != null && (
                            <div
                                className="absolute left-0 top-0 h-full rounded bg-accent"
                                style={{ width: `${Math.min(100, (aggregate / max) * 100)}%` }}
                            />
                        )}
                        <div
                            className="absolute top-[-3px] h-4 w-0.5 bg-border-bold"
                            style={{ left: `${Math.max(0, Math.min(100, (goal / max) * 100))}%` }}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
