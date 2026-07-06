import { useValues } from 'kea'
import { useCallback } from 'react'

import { getBarColorFromStatus } from 'lib/colors'
import { getCurrencySymbol } from 'lib/utils/currency'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { teamLogic } from 'scenes/teamLogic'

import type { RevenueAnalyticsMRRQueryResultItem } from '~/queries/schema/schema-general'
import { GraphDataset } from '~/types'

import { RevenueAnalyticsChart } from '../RevenueAnalyticsChart'
import { extractLabelAndDatasets } from '../shared'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

type RevenueAnalyticsStatus = `revenue-analytics-${keyof RevenueAnalyticsMRRQueryResultItem}`

export function MRRBreakdownChart(): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { data, newDatasets, expansionDatasets, contractionDatasets, churnDatasets } =
        useValues(mrrBreakdownModalLogic)
    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const getColor = useCallback(
        (dataset: GraphDataset) => getBarColorFromStatus(dataset.status as RevenueAnalyticsStatus),
        []
    )

    if (!data || data.length === 0) {
        return <div>No data available</div>
    }

    const { labels, datasets } = extractLabelAndDatasets([
        ...newDatasets.map((dataset) => ({ ...dataset, status: 'revenue-analytics-new' })),
        ...expansionDatasets.map((dataset) => ({ ...dataset, status: 'revenue-analytics-expansion' })),
        ...contractionDatasets.map((dataset) => ({ ...dataset, status: 'revenue-analytics-contraction' })),
        ...churnDatasets.map((dataset) => ({ ...dataset, status: 'revenue-analytics-churn' })),
    ])

    // Make sure they're properly sorted by id in the order we want above
    const datasetsWithIds: GraphDataset[] = datasets.map(
        (dataset, idx) =>
            ({
                ...dataset,
                id: idx,
                action: { ...dataset.action, order: idx }, // Required to make SeriesLetter work as expected
            }) as GraphDataset
    )

    const trendsFilter = {
        aggregationAxisFormat: 'numeric' as const,
        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
    }

    return (
        <div className="w-full">
            <InsightsWrapper>
                <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                    <RevenueAnalyticsChart
                        dataAttr="mrr-breakdown-chart"
                        datasets={datasetsWithIds}
                        labels={labels}
                        kind="bar"
                        divergingStack
                        getColor={getColor}
                        // No `legend` prop: the modal renders its own descriptive MRRLegend above the
                        // chart, so the chart's built-in legend would duplicate it.
                        trendsFilter={trendsFilter}
                    />
                </div>
            </InsightsWrapper>
        </div>
    )
}
