import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue, reportMetricAggregate } from '../../utils/reportMetrics'

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
    const formattedAggregate = formatReportMetricValue(metric, aggregate)
    const snapshot = formatReportMetricValue(metric, metric.value)
    const formattedComparison = metric.comparison ? formatReportMetricValue(metric, metric.comparison.value) : null
    const responseResolved = response !== null && response !== undefined

    return (
        <LemonCard
            hoverEffect={false}
            className="@container/report-primary-metric flex flex-col gap-3 p-3"
            data-attr="report-primary-metric"
        >
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-sm font-semibold text-primary">{metric.title}</h2>
                {metric.caption ? <p className="m-0 text-xs text-tertiary">{metric.caption}</p> : null}
            </div>
            <div className="flex min-w-0 flex-col gap-4 @min-[36rem]/report-primary-metric:flex-row">
                <div className="flex min-h-20 min-w-0 flex-col justify-center @min-[36rem]/report-primary-metric:w-48 @min-[36rem]/report-primary-metric:shrink-0">
                    {responseLoading && !responseResolved ? (
                        <div className="flex items-center gap-2 text-xs text-tertiary">
                            <Spinner className="text-lg" />
                            <span>Loading current value</span>
                        </div>
                    ) : responseError ? (
                        <>
                            {snapshot ? (
                                <div className="text-2xl font-semibold leading-tight tabular-nums text-primary">
                                    {snapshot}
                                </div>
                            ) : null}
                            <p className="m-0 text-xs text-tertiary">
                                Couldn't refresh this metric.
                                {snapshot ? ' Showing the latest saved value.' : null} Refresh the page to try again.
                            </p>
                            {snapshot && metric.value_at ? (
                                <span className="text-xs text-tertiary">
                                    Measured <TZLabel time={metric.value_at} />
                                </span>
                            ) : null}
                            {snapshot && metric.comparison && formattedComparison ? (
                                <span className="text-xs text-tertiary">
                                    {metric.comparison.label}: {formattedComparison}
                                </span>
                            ) : null}
                        </>
                    ) : formattedAggregate ? (
                        <>
                            <div className="text-2xl font-semibold leading-tight tabular-nums text-primary">
                                {formattedAggregate}
                            </div>
                            <span className="text-xs text-tertiary">Current window</span>
                        </>
                    ) : snapshot ? (
                        <>
                            <div className="text-2xl font-semibold leading-tight tabular-nums text-primary">
                                {snapshot}
                            </div>
                            <p className="m-0 text-xs text-tertiary">
                                No value for this window. Showing the latest saved value.
                            </p>
                            {metric.value_at ? (
                                <span className="text-xs text-tertiary">
                                    Measured <TZLabel time={metric.value_at} />
                                </span>
                            ) : null}
                            {metric.comparison && formattedComparison ? (
                                <span className="text-xs text-tertiary">
                                    {metric.comparison.label}: {formattedComparison}
                                </span>
                            ) : null}
                        </>
                    ) : (
                        <span className="text-xs text-tertiary">No value for this window.</span>
                    )}
                </div>
                <div className="flex h-48 min-w-0 flex-col overflow-hidden @min-[36rem]/report-primary-metric:flex-1">
                    <Query query={barQuery} uniqueKey={metricKey} context={{ insightProps }} readOnly embedded />
                </div>
            </div>
        </LemonCard>
    )
}
