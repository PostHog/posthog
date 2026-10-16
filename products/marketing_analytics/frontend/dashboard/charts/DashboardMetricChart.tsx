import { useActions, useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { displayBreakdownValue } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { MarketingQueryError } from '../MarketingQueryError'
import { MetricChart } from './MetricChart'

export function DashboardMetricChart(): JSX.Element | null {
    const { expandedMetricSpec, metricChartQuery, chartMode, focusedBreakdownValue, breakdownLabel, timezone } =
        useValues(marketingDashboardLogic)
    const { setChartMode, setFocusedBreakdownValue } = useActions(marketingDashboardLogic)
    const logic = dataNodeLogic({
        query: metricChartQuery ?? { kind: NodeKind.TrendsQuery, series: [] },
        key: 'marketing-dashboard-metric-chart',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
        autoLoad: !!metricChartQuery,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { loadData } = useActions(logic)
    if (!expandedMetricSpec || !metricChartQuery) {
        return null
    }
    const results = (response as { results?: TrendResult[] } | undefined)?.results ?? []
    return (
        <MetricChart
            label={expandedMetricSpec.label}
            breakdownLabel={breakdownLabel}
            format={expandedMetricSpec.format}
            timezone={timezone}
            labels={results[0]?.days ?? []}
            series={results.map((row) => {
                const key = chartMode === 'breakdown' ? String(row.breakdown_value ?? '') : expandedMetricSpec.label
                return {
                    key,
                    label: chartMode === 'breakdown' ? displayBreakdownValue(key, breakdownLabel) : key,
                    // Trends formulas return percent units; the shared chart formats fractional rates.
                    data:
                        expandedMetricSpec.format === 'percentage'
                            ? (row.data ?? []).map((value) => value / 100)
                            : (row.data ?? []),
                }
            })}
            chartMode={chartMode}
            focusedBreakdownValue={focusedBreakdownValue}
            loading={responseLoading}
            error={
                responseError ? (
                    <MarketingQueryError
                        message="Couldn't load this chart. Change the metric and try again."
                        queryId={responseErrorObject?.queryId ?? queryId}
                        onRetry={() => loadData('force_async')}
                        loading={responseLoading}
                    />
                ) : null
            }
            onChartModeChange={setChartMode}
            onFocus={setFocusedBreakdownValue}
        />
    )
}
