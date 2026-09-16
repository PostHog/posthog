import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WebOverviewItem, WebOverviewQuery, WebOverviewQueryResponse } from '~/queries/schema/schema-general'

import { MarketingMetricCard } from './MarketingMetricCard'
import type { MetricCardSpec } from './metricCardSpec'

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
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    if (responseError && !responseLoading) {
        return (
            <LemonBanner
                type="error"
                className="col-span-full"
                action={{ children: 'Retry', onClick: () => loadData('force_async') }}
            >
                Couldn't load these metrics. Try again.
            </LemonBanner>
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
                    spec={spec}
                    loading={false}
                    labelFromKey={labelFromKey}
                />
            ))}
        </>
    )
}
