import { useValues } from 'kea'
import { range } from 'lib/utils'
import { useState } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsInsightsQuery,
    RevenueAnalyticsInsightsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

const NUM_SKELETONS = 3

let uniqueNode = 0
export function RevenueAnalyticsInsightsNode(props: {
    query: RevenueAnalyticsInsightsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
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

    const { response, responseLoading } = useValues(logic)
    const queryResponse = response as RevenueAnalyticsInsightsQueryResponse | undefined

    const results = responseLoading ? range(NUM_SKELETONS).map(() => undefined) : queryResponse?.results ?? []

    return (
        <div className="flex flex-row flex-wrap md:flex-nowrap w-full gap-2">
            TODO
            {JSON.stringify(results)}
        </div>
    )
}
