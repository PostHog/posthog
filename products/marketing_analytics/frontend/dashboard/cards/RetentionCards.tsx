import { useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRetentionQueryResponse } from '~/queries/schema/schema-general'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { RetentionTotals, retentionTotals } from '../marketingDashboardMetrics'
import { MarketingMetricCard } from './MarketingMetricCard'
import { MetricCardSpec, pctChange } from './metricCardSpec'

const RETENTION_LABELS: Record<string, string> = {
    acquired: 'New visitors',
    return7: '7-day return rate',
    return30: '30-day return rate',
    medianReturnDays: 'Median days to return',
}

const rate = (returned: number, eligible: number): number | undefined =>
    eligible ? (returned / eligible) * 100 : undefined

/** A rate with nobody eligible yet is not zero, so it reads as a notice rather than a number. */
const rateSpec = (key: string, days: 7 | 30, totals: RetentionTotals): MetricCardSpec => {
    const value = days === 7 ? rate(totals.returned7d, totals.eligible7d) : rate(totals.returned30d, totals.eligible30d)
    const previous =
        days === 7
            ? rate(totals.previousReturned7d, totals.previousEligible7d)
            : rate(totals.previousReturned30d, totals.previousEligible30d)
    if (value === undefined) {
        return {
            kind: 'notice',
            key,
            title: RETENTION_LABELS[key],
            message: `Nobody has had the full ${days} days yet. Widen the date range to see this.`,
        }
    }
    return {
        kind: 'metric',
        item: { key, kind: 'percentage', value, previous, changeFromPreviousPct: pctChange(value, previous) } as never,
    }
}

export interface RetentionCardsProps {
    /** Renders a single card, for the Overview where retention is one metric among five. */
    only?: 'acquired' | 'return7' | 'return30' | 'medianReturnDays'
}

export function RetentionCards({ only }: RetentionCardsProps = {}): JSX.Element {
    const { retentionQuery } = useValues(marketingDashboardLogic)
    const logic = dataNodeLogic({
        query: retentionQuery,
        key: 'marketing-dashboard-retention',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading } = useValues(logic)

    if (responseLoading) {
        return (
            <>
                {Array.from({ length: only ? 1 : 4 }, (_, index) => (
                    <MarketingMetricCard key={index} loading labelFromKey={(key) => RETENTION_LABELS[key] ?? key} />
                ))}
            </>
        )
    }

    const totals = retentionTotals((response as MarketingAnalyticsRetentionQueryResponse | undefined)?.summary)
    const specs: MetricCardSpec[] = [
        {
            kind: 'metric',
            item: {
                key: 'acquired',
                kind: 'unit',
                value: totals.acquired,
                previous: totals.previousAcquired || undefined,
                changeFromPreviousPct: pctChange(totals.acquired, totals.previousAcquired || undefined),
            } as never,
        },
        rateSpec('return7', 7, totals),
        rateSpec('return30', 30, totals),
        totals.medianReturnDays === null
            ? {
                  kind: 'notice',
                  key: 'medianReturnDays',
                  title: RETENTION_LABELS.medianReturnDays,
                  message: 'No second sessions seen within 30 days yet.',
              }
            : {
                  kind: 'metric',
                  item: {
                      key: 'medianReturnDays',
                      kind: 'unit',
                      value: totals.medianReturnDays,
                      previous: totals.previousMedianReturnDays ?? undefined,
                      changeFromPreviousPct: pctChange(
                          totals.medianReturnDays,
                          totals.previousMedianReturnDays ?? undefined
                      ),
                  } as never,
              },
    ]

    const shown = only ? specs.filter((spec) => (spec.kind === 'metric' ? spec.item.key : spec.key) === only) : specs

    return (
        <>
            {shown.map((spec) => (
                <MarketingMetricCard
                    key={spec.kind === 'metric' ? spec.item.key : spec.key}
                    spec={spec}
                    loading={false}
                    labelFromKey={(key) => RETENTION_LABELS[key] ?? key}
                />
            ))}
        </>
    )
}
