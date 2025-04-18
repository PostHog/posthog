import { BindLogic, useValues } from 'kea'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'

import { revenueEventsSettingsLogic } from '../settings/revenueEventsSettingsLogic'

let uniqueNode = 0
export function RevenueAnalyticsTopCustomersNode(props: {
    query: RevenueAnalyticsTopCustomersQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsTopCustomers.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { baseCurrency } = useValues(revenueEventsSettingsLogic)
    const { response, responseLoading, queryId } = useValues(logic)

    // TODO: Figure out what `insightProps` should be
    if (responseLoading) {
        return <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
    }

    // `results` is an array of array in order [customer_name, customer_id, revenue, month]
    const queryResponse = response as RevenueAnalyticsTopCustomersQueryResponse | undefined
    const results = (queryResponse?.results ?? []) as any[][]

    const resultsGroupedByCustomer: Record<string, Record<string, any>> = {}
    for (const result of results) {
        const [, id, , month] = result
        resultsGroupedByCustomer[id] ||= {}
        resultsGroupedByCustomer[id][month] = result
    }

    const labels: string[] = Array.from(new Set(results.map((result) => result[3]))).sort() as string[]
    const datasets: GraphDataset[] = Object.entries(resultsGroupedByCustomer).map(([_, results], idx) => {
        const key = Object.keys(results)[0]

        return {
            id: idx + 1, // Make them start at 1, for good measure

            // Name is in first column, grab from any result
            // Fallback to second column if first is undefined, that's the customer_id
            label: results[key][0] ?? results[key][1],

            // In the same order as the labels get the revenue
            // assuming it was 0 if not present in the dataset
            data: labels.map((label) => results[label]?.[2] ?? 0),

            // Color stuff, make it look pretty
            colorIndex: idx,
        }
    })

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

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
                            isInProgress
                            trendsFilter={{
                                aggregationAxisFormat: 'numeric',
                                decimalPlaces: 2,
                                minDecimalPlaces: 2,
                                aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                                aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                            }}
                            incompletenessOffsetFromEnd={1}
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
