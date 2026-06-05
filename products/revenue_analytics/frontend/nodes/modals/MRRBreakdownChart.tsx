import { useValues } from 'kea'

import { getBarColorFromStatus } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { teamLogic } from 'scenes/teamLogic'

import type { RevenueAnalyticsMRRQueryResultItem } from '~/queries/schema/schema-general'
import { GraphDataset, GraphType } from '~/types'

import { revenueAnalyticsLogic } from '../../revenueAnalyticsLogic'
import { RevenueAnalyticsChart } from '../RevenueAnalyticsChart'
import { extractLabelAndDatasets } from '../shared'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

type RevenueAnalyticsStatus = `revenue-analytics-${keyof RevenueAnalyticsMRRQueryResultItem}`

export function MRRBreakdownChart(): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { dateFilter } = useValues(revenueAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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

    const trendsFilter = {
        aggregationAxisFormat: 'numeric' as const,
        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
    }

    return (
        <div className="w-full">
            <InsightsWrapper>
                <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                    {featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_QUILL_CHARTS] ? (
                        <RevenueAnalyticsChart
                            dataAttr="mrr-breakdown-chart"
                            datasets={datasetsWithIds}
                            labels={labels}
                            kind="bar"
                            divergingStack
                            // The modal renders its own descriptive MRRLegend above the chart, so we
                            // don't show the chart's built-in legend (it would duplicate it).
                            getColor={(dataset) => getBarColorFromStatus(dataset.status as RevenueAnalyticsStatus)}
                            trendsFilter={trendsFilter}
                        />
                    ) : (
                        <LineGraph
                            datasets={datasetsWithIds}
                            labels={labels}
                            type={GraphType.Bar}
                            data-attr="mrr-breakdown-chart"
                            labelGroupType="none"
                            isStacked={true}
                            isInProgress={!dateFilter.dateTo}
                            legend={{ display: true, position: 'right' }}
                            trendsFilter={trendsFilter}
                        />
                    )}
                </div>
            </InsightsWrapper>
        </div>
    )
}
