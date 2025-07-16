import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsArpuQuery,
    RevenueAnalyticsArpuQueryResponse,
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
export function RevenueAnalyticsArpuNode(props: {
    query: RevenueAnalyticsArpuQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsArpu.${uniqueNode++}`)
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
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <ArpuTile
                    response={response as RevenueAnalyticsArpuQueryResponse}
                    responseLoading={responseLoading}
                    queryId={queryId ?? ''}
                    context={props.context}
                />
            </BindLogic>
        </BindLogic>
    )
}

const ARPU_TITLE = 'ARPU'
const ARPU_TOOLTIP = (
    <span>
        The average revenue per user in each period. This is calculated by dividing the total revenue by the number of
        customers.
    </span>
)
const ArpuTile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsArpuQueryResponse>): JSX.Element => {
    const { insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const results = (response?.results as GraphDataset[]) ?? []
    const { labels, datasets } = extractLabelAndDatasets(results)

    return (
        <TileWrapper
            title={ARPU_TITLE}
            tooltip={ARPU_TOOLTIP}
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
                    data-attr="revenue-analytics-arpu-tile-graph"
                    datasets={datasets}
                    labels={labels}
                />
            )}
        </TileWrapper>
    )
}
