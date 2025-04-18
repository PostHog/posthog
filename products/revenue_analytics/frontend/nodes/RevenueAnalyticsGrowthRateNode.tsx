import { BindLogic, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
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

let uniqueNode = 0
export function RevenueAnalyticsGrowthRateNode(props: {
    query: RevenueAnalyticsGrowthRateQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
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

    // TODO: Figure out what `insightProps` should be
    if (responseLoading) {
        return <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
    }

    // `results` is an array of array in order [month, mrr, previous_mrr, growth_rate, 3m_growth_rate, 6m_growth_rate]
    const queryResponse = response as RevenueAnalyticsGrowthRateQueryResponse | undefined

    // Remove first entry, it won't have any growth information
    const results = ((queryResponse?.results ?? []) as any[][]).slice(1)

    const labels: string[] = Array.from(new Set(results.map((result) => result[0]))).sort() as string[]
    const datasets: (GraphDataset & { colorIndex: number })[] = [
        {
            id: 1,
            label: 'Growth Rate',
            data: results.map((result) => result[3] * 100),
            colorIndex: 0,
        },
        {
            id: 2,
            label: '3 Month Growth Rate',
            data: results.map((result) => result[4] * 100),
            colorIndex: 1,
        },
        {
            id: 3,
            label: '6 Month Growth Rate',
            data: results.map((result) => result[5] * 100),
            colorIndex: 2,
        },
    ]

    return (
        <div className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary">
            <div className="InsightVizDisplay__content">
                <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                    <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                        <LineGraph
                            data-attr="revenue-analytics-top-customers-node-graph"
                            type={GraphType.Line}
                            datasets={datasets}
                            labels={labels}
                            trendsFilter={{ aggregationAxisFormat: 'percentage' }}
                            labelGroupType="none"
                        />
                    </BindLogic>
                </BindLogic>
            </div>
        </div>
    )

    return <div>{JSON.stringify({ response, responseLoading })}</div>

    // const results = responseLoading ? range(NUM_SKELETONS).map(() => undefined) : queryResponse?.results ?? []

    // return (
    //     <div className="grid auto-cols-fr grid-flow-col w-full gap-2">
    //         {results.map((item, index) => (
    //             <div key={item?.key ?? index} className={cn(HEIGHT_CLASS, { [REVENUE_CONTAINER_CLASS]: index === 0 })}>
    //                 <ItemCell item={item} />
    //             </div>
    //         ))}
    //     </div>
    // )
}
