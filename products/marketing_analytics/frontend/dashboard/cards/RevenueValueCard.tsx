import { useActions, useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { sumTrendSeries } from '../marketingDashboardMetrics'
import { MarketingQueryError } from '../MarketingQueryError'
import { MarketingMetricCard } from './MarketingMetricCard'
import { pctChange } from './metricCardSpec'

export function RevenueValueCard({ query }: { query: TrendsQuery }): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: 'marketing-dashboard-revenue',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { loadData } = useActions(logic)

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

    const results = (response as { results?: TrendResult[] } | undefined)?.results
    const { value, previous } = sumTrendSeries(results)

    return (
        <MarketingMetricCard
            loading={responseLoading || (!response && !responseError)}
            labelFromKey={() => 'Revenue'}
            spec={{
                kind: 'metric',
                item: {
                    key: 'revenue',
                    kind: 'currency',
                    value,
                    previous,
                    changeFromPreviousPct: pctChange(value, previous),
                } as never,
            }}
        />
    )
}
