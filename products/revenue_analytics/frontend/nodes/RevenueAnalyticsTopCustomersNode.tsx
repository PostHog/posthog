import { BindLogic, BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'

let uniqueNode = 0
export function RevenueAnalyticsTopCustomersNode(props: {
    query: RevenueAnalyticsTopCustomersQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { dateFilter } = useValues(revenueAnalyticsLogic)
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

    useAttachedLogic(logic, props.attachTo)

    const { baseCurrency } = useValues(teamLogic)
    const { response, responseLoading, queryId } = useValues(logic)

    if (responseLoading) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
            </InsightsWrapper>
        )
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

            // Name is in the second column, grab from any result
            // Fallback to first column if second is undefined, that's the customer_id
            label: results[key][1] ?? results[key][0],

            // In the same order as the labels get the revenue
            // assuming it was 0 if not present in the dataset
            data: labels.map((label) => results[label]?.[2] ?? 0),

            // Color stuff, make it look pretty
            colorIndex: idx,
        }
    })

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    // These classes are all pretty weird but they're here because we want to maintain consistency
    // between the trends and top customers views
    return (
        <InsightsWrapper>
            <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                    <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                        <LineGraph
                            data-attr="revenue-analytics-top-customers-node-graph"
                            type={GraphType.Line}
                            datasets={datasets}
                            labels={labels}
                            isInProgress={!dateFilter.dateTo}
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
        </InsightsWrapper>
    )
}
