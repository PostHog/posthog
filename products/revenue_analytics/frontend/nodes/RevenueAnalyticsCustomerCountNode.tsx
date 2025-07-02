import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsCustomerCountQuery,
    RevenueAnalyticsCustomerCountQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'

import { DisplayMode, revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { DISPLAY_MODE_OPTIONS, TileProps, TileWrapper } from './components'

const DISPLAY_MODE_TO_GRAPH_TYPE: Record<DisplayMode, GraphType> = {
    line: GraphType.Line,
    area: GraphType.Line,
    bar: GraphType.Bar,

    // not really supported, but here to satisfy the type checker
    table: GraphType.Line,
}

let uniqueNode = 0
export function RevenueAnalyticsCustomerCountNode(props: {
    query: RevenueAnalyticsCustomerCountQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsCustomerCount.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                    <SubscriptionCountTile
                        response={response as RevenueAnalyticsCustomerCountQueryResponse}
                        responseLoading={responseLoading}
                        queryId={queryId ?? ''}
                        context={props.context}
                    />
                    <CustomerCountTile
                        response={response as RevenueAnalyticsCustomerCountQueryResponse}
                        responseLoading={responseLoading}
                        queryId={queryId ?? ''}
                        context={props.context}
                    />
                </BindLogic>
            </BindLogic>
        </div>
    )
}

const SUBSCRIPTION_COUNT_TITLE = 'Subscriptions'
const SUBSCRIPTION_COUNT_TOOLTIP = (
    <span>
        The number of subscriptions that you had in each period. It also includes the number of new and churned
        subscriptions in that period.
    </span>
)

const SubscriptionCountTile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsCustomerCountQueryResponse>): JSX.Element => {
    const { insightsDisplayMode, dateFilter } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const results = ((response?.results as GraphDataset[]) ?? []).filter((result) =>
        result.label?.includes('Subscription Count')
    )
    const labels = results[0]?.labels ?? []
    const datasets: GraphDataset[] = results.map((result, index) => ({
        ...result,
        seriesIndex: index,
    }))

    return (
        <TileWrapper
            title={SUBSCRIPTION_COUNT_TITLE}
            tooltip={SUBSCRIPTION_COUNT_TOOLTIP}
            extra={
                <div className="flex items-center gap-1 text-muted-alt">
                    <LemonSegmentedButton
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                        size="small"
                    />
                </div>
            }
        >
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <LineGraph
                    data-attr="revenue-analytics-subscription-count-tile-graph"
                    type={DISPLAY_MODE_TO_GRAPH_TYPE[insightsDisplayMode]}
                    datasets={datasets}
                    labels={labels}
                    isArea={insightsDisplayMode !== 'line'}
                    isInProgress={!dateFilter.dateTo}
                    legend={{ display: true, position: 'right' }}
                    trendsFilter={{ aggregationAxisFormat: 'numeric' }}
                    labelGroupType="none"
                />
            )}
        </TileWrapper>
    )
}

const CUSTOMER_COUNT_TITLE = 'Customers'
const CUSTOMER_COUNT_TOOLTIP = (
    <span>
        The number of customers that you had in each period. This might differ from the number of subscriptions because
        a customer can have multiple subscriptions.
    </span>
)
const CustomerCountTile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsCustomerCountQueryResponse>): JSX.Element => {
    const { insightsDisplayMode, dateFilter } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const results = ((response?.results as GraphDataset[]) ?? []).filter((result) =>
        result.label?.includes('Customer Count')
    )
    const labels = results[0]?.labels ?? []
    const datasets: GraphDataset[] = results.map((result, index) => ({
        ...result,
        seriesIndex: index,
    }))

    return (
        <TileWrapper
            title={CUSTOMER_COUNT_TITLE}
            tooltip={CUSTOMER_COUNT_TOOLTIP}
            extra={
                <div className="flex items-center gap-1 text-muted-alt">
                    <LemonSegmentedButton
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                        size="small"
                    />
                </div>
            }
        >
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <LineGraph
                    data-attr="revenue-analytics-customer-count-tile-graph"
                    type={DISPLAY_MODE_TO_GRAPH_TYPE[insightsDisplayMode]}
                    datasets={datasets}
                    labels={labels}
                    isArea={insightsDisplayMode !== 'line'}
                    isInProgress={!dateFilter.dateTo}
                    legend={{ display: true, position: 'right' }}
                    trendsFilter={{ aggregationAxisFormat: 'numeric' }}
                    labelGroupType="none"
                />
            )}
        </TileWrapper>
    )
}
