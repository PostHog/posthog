import { useActions, useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WebOverviewItem, WebOverviewQuery, WebOverviewQueryResponse } from '~/queries/schema/schema-general'

import { MarketingQueryError } from '../MarketingQueryError'
import { MarketingMetricCard } from './MarketingMetricCard'
import type { MetricCardSpec } from './metricCardSpec'
import { useCardExpansion } from './useCardExpansion'

export interface WebOverviewCardsProps {
    query: WebOverviewQuery
    dataNodeKey: string
    select: (results: WebOverviewItem[] | undefined) => MetricCardSpec[]
    numSkeletons: number
    labelFromKey: (key: string) => React.ReactNode
}

export function WebOverviewCards({
    query,
    dataNodeKey,
    select,
    numSkeletons,
    labelFromKey,
}: WebOverviewCardsProps): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: dataNodeKey,
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { loadData } = useActions(logic)
    const expandable = useCardExpansion()

    if (responseError && !responseLoading) {
        return (
            <div className="col-span-full">
                <MarketingQueryError
                    message="Couldn't load these metrics. Try again."
                    queryId={responseErrorObject?.queryId ?? queryId}
                    onRetry={() => loadData('force_async')}
                    loading={responseLoading}
                />
            </div>
        )
    }

    if (responseLoading) {
        return (
            <>
                {Array.from({ length: numSkeletons }, (_, index) => (
                    <MarketingMetricCard key={index} loading labelFromKey={labelFromKey} />
                ))}
            </>
        )
    }

    return (
        <>
            {select((response as WebOverviewQueryResponse | undefined)?.results).map((spec) => (
                <MarketingMetricCard
                    key={spec.kind === 'metric' ? spec.item.key : spec.key}
                    spec={expandable(spec)}
                    loading={false}
                    labelFromKey={labelFromKey}
                />
            ))}
        </>
    )
}
