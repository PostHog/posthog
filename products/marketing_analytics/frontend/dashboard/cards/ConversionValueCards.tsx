import { useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery, WebOverviewQueryResponse } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { sumTrendSeries } from '../marketingDashboardMetrics'
import { MarketingMetricCard } from './MarketingMetricCard'
import { pctChange } from './metricCardSpec'
import { MetricNoticeCard } from './MetricNoticeCard'

const LABELS: Record<string, string> = {
    conversion_value: 'Conversion value',
    avg_conversion_value: 'Avg. conversion value',
}

const NO_VALUE_MESSAGE = 'No value associated with this conversion.'

/** Both value cards, or a pair of N/A notices when the goal totals no money property. */
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
    const { conversionOverviewQuery } = useValues(marketingDashboardLogic)
    const valueLogic = dataNodeLogic({
        query,
        key: 'marketing-dashboard-conversion-value',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response: valueResponse, responseLoading: valueLoading } = useValues(valueLogic)

    // Conversions come from the overview node the section already mounts, so the average is a
    // division rather than a third request.
    const conversionsLogic = dataNodeLogic({
        query: conversionOverviewQuery!,
        key: 'marketing-dashboard-conversion-overview',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response: conversionsResponse, responseLoading: conversionsLoading } = useValues(conversionsLogic)

    const { value, previous } = sumTrendSeries((valueResponse as { results?: TrendResult[] } | undefined)?.results)
    const conversions = (conversionsResponse as WebOverviewQueryResponse | undefined)?.results?.find(
        (item) => item.key === 'total conversions'
    )
    const average = conversions?.value ? value / conversions.value : undefined
    const previousAverage =
        previous !== undefined && conversions?.previous ? previous / conversions.previous : undefined

    return (
        <>
            <MarketingMetricCard
                loading={valueLoading}
                labelFromKey={(key) => LABELS[key] ?? key}
                spec={{
                    kind: 'metric',
                    item: {
                        key: 'conversion_value',
                        kind: 'currency',
                        value,
                        previous,
                        changeFromPreviousPct: pctChange(value, previous),
                    } as never,
                }}
            />
            <MarketingMetricCard
                loading={valueLoading || conversionsLoading}
                labelFromKey={(key) => LABELS[key] ?? key}
                spec={{
                    kind: 'metric',
                    item: {
                        key: 'avg_conversion_value',
                        kind: 'currency',
                        value: average,
                        previous: previousAverage,
                        changeFromPreviousPct: pctChange(average, previousAverage),
                    } as never,
                }}
            />
        </>
    )
}
