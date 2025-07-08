import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsCustomerCountQuery,
    RevenueAnalyticsCustomerCountQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import {
    DISPLAY_MODE_OPTIONS,
    extractLabelAndDatasets,
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
} from './shared'

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
    const { insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const results = ((response?.results as GraphDataset[]) ?? []).filter((result) =>
        result.label?.includes('Subscription Count')
    )

    const { labels, datasets } = extractLabelAndDatasets(results)

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
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-subscription-count-tile-graph"
                    datasets={datasets}
                    labels={labels}
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
    const { insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const results = ((response?.results as GraphDataset[]) ?? []).filter((result) =>
        result.label?.includes('Customer Count')
    )

    const { labels, datasets } = extractLabelAndDatasets(results)

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
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-customer-count-tile-graph"
                    datasets={datasets}
                    labels={labels}
                />
            )}
        </TileWrapper>
    )
}
