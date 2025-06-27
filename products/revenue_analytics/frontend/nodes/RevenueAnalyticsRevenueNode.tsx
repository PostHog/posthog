import { useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsRevenueQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

let uniqueNode = 0
export function RevenueAnalyticsRevenueNode(props: {
    query: RevenueAnalyticsRevenueQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsRevenue.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)
    const queryResponse = response as RevenueAnalyticsRevenueQueryResponse | undefined

    if (responseLoading) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context.insightProps ?? {}} />
            </InsightsWrapper>
        )
    }

    return (
        <InsightsWrapper>
            RevenueAnalyticsRevenueNode
            <pre>{JSON.stringify(queryResponse, null, 2)}</pre>
        </InsightsWrapper>
    )
}
