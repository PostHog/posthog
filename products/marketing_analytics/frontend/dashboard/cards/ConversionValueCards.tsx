import { useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { seriesTotal } from '../marketingDashboardMetrics'
import { MarketingMetricCard } from './MarketingMetricCard'
import { pctChange } from './metricCardSpec'
import { MetricNoticeCard } from './MetricNoticeCard'

const LABELS: Record<string, string> = {
    conversion_value: 'Conversion value',
    avg_conversion_value: 'Avg. conversion value',
}

const NO_VALUE_MESSAGE = 'No value associated with this conversion.'

/** The value total and its average, or a pair of N/A notices when the goal totals no money
 * property. Both come from one query, so they cannot disagree with each other. */
export function ConversionValueCards(): JSX.Element {
    const { conversionValueQuery } = useValues(marketingDashboardLogic)

    if (!conversionValueQuery) {
        return (
            <>
                {(['conversion_value', 'avg_conversion_value'] as const).map((key) => (
                    <MetricNoticeCard key={key} title={LABELS[key]} message={NO_VALUE_MESSAGE} value="N/A" />
                ))}
            </>
        )
    }
    return <ConversionValueLoaded query={conversionValueQuery} />
}

function ConversionValueLoaded({ query }: { query: TrendsQuery }): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: 'marketing-dashboard-conversion-value',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading } = useValues(logic)

    const results = (response as { results?: TrendResult[] } | undefined)?.results
    // Series order, not label: the query asks for the sum first and the average second.
    const total = seriesTotal(results, 0)
    const average = seriesTotal(results, 1)

    const card = (key: string, amount: { value?: number; previous?: number }): JSX.Element =>
        amount.value === undefined ? (
            <MetricNoticeCard
                key={key}
                title={LABELS[key]}
                message="No conversions with a value in this range."
                value="N/A"
            />
        ) : (
            <MarketingMetricCard
                key={key}
                loading={responseLoading}
                labelFromKey={(k) => LABELS[k] ?? k}
                spec={{
                    kind: 'metric',
                    item: {
                        key,
                        kind: 'currency',
                        value: amount.value,
                        previous: amount.previous,
                        changeFromPreviousPct: pctChange(amount.value, amount.previous),
                    } as never,
                }}
            />
        )

    if (responseLoading) {
        return (
            <>
                {(['conversion_value', 'avg_conversion_value'] as const).map((key) => (
                    <MarketingMetricCard key={key} loading labelFromKey={(k) => LABELS[k] ?? k} />
                ))}
            </>
        )
    }

    return (
        <>
            {card('conversion_value', total)}
            {card('avg_conversion_value', average)}
        </>
    )
}
