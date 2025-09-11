import { useValues } from 'kea'

import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { teamLogic } from 'scenes/teamLogic'

import { GraphDataset, GraphType } from '~/types'

import { revenueAnalyticsLogic } from '../../revenueAnalyticsLogic'
import { extractLabelAndDatasets } from '../shared'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

export function MRRBreakdownChart(): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { dateFilter } = useValues(revenueAnalyticsLogic)
    const { data, newDatasets, expansionDatasets, contractionDatasets, churnDatasets } =
        useValues(mrrBreakdownModalLogic)
    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

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

    return (
        <div className="w-full">
            <InsightsWrapper>
                <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                    <LineGraph
                        datasets={datasetsWithIds}
                        labels={labels}
                        type={GraphType.Bar}
                        data-attr="mrr-breakdown-chart"
                        labelGroupType="none"
                        isStacked={true}
                        isInProgress={!dateFilter.dateTo}
                        legend={{
                            display: true,
                            position: 'right',
                        }}
                        trendsFilter={{
                            aggregationAxisFormat: 'numeric',
                            aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                            aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                        }}
                    />
                </div>
            </InsightsWrapper>
        </div>
    )
}
