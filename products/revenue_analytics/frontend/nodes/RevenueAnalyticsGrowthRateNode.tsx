import { BindLogic, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsGrowthRateQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'
import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'

let uniqueNode = 0
export function RevenueAnalyticsGrowthRateNode(props: {
    query: RevenueAnalyticsGrowthRateQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { dateFilter } = useValues(revenueAnalyticsLogic)
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsGrowthRate.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)

    if (responseLoading) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
            </InsightsWrapper>
        )
    }

    // `results` is an array of array in order [month, mrr, previous_mrr, growth_rate, 3m_growth_rate, 6m_growth_rate]
    const queryResponse = response as RevenueAnalyticsGrowthRateQueryResponse | undefined

    // Remove first entry, it won't have any growth information
    const results = ((queryResponse?.results ?? []) as any[][]).slice(1)

    const labels: string[] = Array.from(new Set(results.map((result) => result[0]))).sort() as string[]
    const datasets: (GraphDataset & { colorIndex: number })[] = [
        {
            id: 0,
            label: 'Growth Rate',
            data: results.map((result) => result[3] * 100),
            colorIndex: 0,
        },
        {
            id: 1,
            label: '3 Month Avg. Growth Rate',
            data: results.map((result) => result[4] * 100),
            colorIndex: 1,
        },
        {
            id: 2,
            label: '6 Month Avg. Growth Rate',
            data: results.map((result) => result[5] * 100),
            colorIndex: 2,
        },
    ]

    return (
        <InsightsWrapper>
            <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                    <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                        <LineGraph
                            data-attr="revenue-analytics-growth-rate-node-graph"
                            type={GraphType.Line}
                            datasets={datasets}
                            labels={labels}
                            isInProgress={!dateFilter.dateTo}
                            trendsFilter={{ aggregationAxisFormat: 'percentage' }}
                            labelGroupType="none"
                        />
                    </BindLogic>
                </BindLogic>
            </div>
        </InsightsWrapper>
    )
}
