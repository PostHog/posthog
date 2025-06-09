import { BindLogic, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsInsightsQuery,
    RevenueAnalyticsInsightsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'

let uniqueNode = 0
export function RevenueAnalyticsInsightsNode(props: {
    query: RevenueAnalyticsInsightsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { baseCurrency, revenueGoals, grossRevenueGroupBy } = useValues(revenueAnalyticsLogic)
    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsInsights.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)
    const queryResponse = response as RevenueAnalyticsInsightsQueryResponse | undefined

    if (responseLoading) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
            </InsightsWrapper>
        )
    }

    const results = (queryResponse?.results as GraphDataset[]) ?? []

    const labels = results[0]?.labels ?? []
    const datasets: GraphDataset[] = results.map((result, index) => ({
        ...result,
        seriesIndex: index,
    }))

    return (
        <InsightsWrapper>
            <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                    <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                        <LineGraph
                            data-attr="revenue-analytics-insights-node-graph"
                            type={grossRevenueGroupBy === 'all' ? GraphType.Line : GraphType.Bar}
                            datasets={datasets}
                            labels={labels}
                            isArea={datasets.length > 1}
                            legend={{
                                display: grossRevenueGroupBy === 'product' && datasets.length > 1,
                                position: 'right',
                                // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                                reverse: true,
                            }}
                            trendsFilter={{
                                aggregationAxisFormat: 'numeric',
                                aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                                aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                                goalLines: revenueGoals.map((goal) => {
                                    const isFuture = dayjs(goal.due_date).isSameOrAfter(dayjs())

                                    return {
                                        label: `${goal.name} (${dayjs(goal.due_date).format('DD MMM YYYY')})`,
                                        value: goal.goal,
                                        displayLabel: true,
                                        borderColor: isFuture ? 'green' : 'red',

                                        // Only display smaller goals that are in the future
                                        // This implies that past goals that have been achieved already
                                        // will not be displayed
                                        displayIfCrossed: isFuture,
                                    }
                                }),
                            }}
                            labelGroupType="none"
                        />
                    </BindLogic>
                </BindLogic>
            </div>
        </InsightsWrapper>
    )
}
