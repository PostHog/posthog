import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { asReportMetricSeriesQuery, reportMetricSeriesPoints } from '../../utils/reportMetrics'
import { ReportObservationChart } from './ReportObservationChart'

export function ReportExpectedImpactChart({
    reportId,
    metric,
    query,
}: {
    reportId: string
    metric: ReportMetricApi
    query: NonNullable<ReturnType<typeof asReportMetricSeriesQuery>>['source']
}): JSX.Element {
    const props: DataNodeLogicProps = {
        key: `ReportMetricSeries.${reportId}.${metric.metric_id}`,
        query,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        autoLoad: true,
    }
    const { response, responseError, responseLoading } = useValues(dataNodeLogic(props))
    const points = reportMetricSeriesPoints(response)

    if (responseLoading && !response) {
        return <LemonSkeleton className="h-36 w-full" />
    }
    if (responseError || !points) {
        return <p className="text-tertiary m-0">No chart data for this window. The goal is still a proposal.</p>
    }

    return (
        <ReportObservationChart
            metric={metric}
            points={points}
            type="line"
            interval={query.interval}
            goalValue={metric.goal_value ?? undefined}
        />
    )
}
