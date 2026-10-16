import { useActions, useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { seriesTotal } from '../marketingDashboardMetrics'
import { MarketingQueryError } from '../MarketingQueryError'
import { MarketingMetricCard } from './MarketingMetricCard'
import { pctChange } from './metricCardSpec'
import { MetricNoticeCard } from './MetricNoticeCard'
import { useCardExpansion } from './useCardExpansion'

export const CONVERSION_VALUE_LABELS: Record<string, string> = {
    conversion_value: 'Conversion value',
    avg_conversion_value: 'Avg. conversion value',
}

export type ConversionValueKey = 'conversion_value' | 'avg_conversion_value'

export function ConversionValueLoaded({
    query,
    keys,
}: {
    query: TrendsQuery
    keys: ConversionValueKey[]
}): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: 'marketing-dashboard-conversion-value',
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

    const results = (response as { results?: TrendResult[] } | undefined)?.results
    // Series order, not label: the query asks for the sum first and the average second.
    const total = seriesTotal(results, 0)
    const average = seriesTotal(results, 1)

    const card = (key: string, amount: { value?: number; previous?: number }): JSX.Element =>
        amount.value === undefined ? (
            <MetricNoticeCard
                key={key}
                title={CONVERSION_VALUE_LABELS[key]}
                message="No conversions with a value in this range."
                value="N/A"
            />
        ) : (
            <MarketingMetricCard
                key={key}
                loading={responseLoading}
                labelFromKey={(k) => CONVERSION_VALUE_LABELS[k] ?? k}
                spec={expandable({
                    kind: 'metric',
                    item: {
                        key,
                        kind: 'currency',
                        value: amount.value,
                        previous: amount.previous,
                        changeFromPreviousPct: pctChange(amount.value, amount.previous),
                    } as never,
                })}
            />
        )

    if (responseLoading || (!response && !responseError)) {
        return (
            <>
                {keys.map((key) => (
                    <MarketingMetricCard key={key} loading labelFromKey={(k) => CONVERSION_VALUE_LABELS[k] ?? k} />
                ))}
            </>
        )
    }

    return <>{keys.map((key) => card(key, key === 'conversion_value' ? total : average))}</>
}
