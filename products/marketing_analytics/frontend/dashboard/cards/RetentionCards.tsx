import { useActions, useValues } from 'kea'

import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    MarketingAnalyticsRetentionQueryResponse,
    WebOverviewItem,
    WebOverviewQueryResponse,
} from '~/queries/schema/schema-general'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { RetentionTotals, retentionTotals } from '../marketingDashboardMetrics'
import { MarketingQueryError } from '../MarketingQueryError'
import { MarketingMetricCard } from './MarketingMetricCard'
import { MetricCardSpec, pctChange } from './metricCardSpec'
import { useCardExpansion } from './useCardExpansion'

const RETENTION_LABELS: Record<string, string> = {
    acquired: 'New visitors',
    returners: 'Returning visitors',
    newVisitorShare: 'New visitor share',
    return7: '7-day return rate',
    return30: '30-day return rate',
    medianReturnDays: 'Median days to return',
}

const RETENTION_CARD_ORDER = ['acquired', 'returners', 'return7', 'return30', 'medianReturnDays']

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
    only?: 'acquired' | 'returners' | 'newVisitorShare' | 'return7' | 'return30' | 'medianReturnDays'
}

/** New visitors over all visitors. A notice rather than zero when the traffic query has no
 * visitors to divide by. */
const newVisitorShareSpec = (totals: RetentionTotals, visitors: WebOverviewItem | undefined): MetricCardSpec => {
    if (!visitors?.value) {
        return {
            kind: 'notice',
            key: 'newVisitorShare',
            title: RETENTION_LABELS.newVisitorShare,
            message: 'No visitors in this range to compare against.',
        }
    }
    const value = (totals.acquired / visitors.value) * 100
    const previous = visitors.previous ? (totals.previousAcquired / visitors.previous) * 100 : undefined
    return {
        kind: 'metric',
        item: {
            key: 'newVisitorShare',
            kind: 'percentage',
            value,
            previous,
            changeFromPreviousPct: pctChange(value, previous),
        } as never,
    }
}

export function RetentionCards({ only }: RetentionCardsProps = {}): JSX.Element {
    const { retentionQuery, retentionTrafficQuery, retentionAcquisitionRange } = useValues(marketingDashboardLogic)
    const expandable = useCardExpansion()
    const logic = dataNodeLogic({
        query: retentionQuery,
        key: 'marketing-dashboard-retention',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { loadData } = useActions(logic)
    const trafficLogic = dataNodeLogic({
        query: retentionTrafficQuery,
        key: 'marketing-dashboard-retention-traffic',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const {
        response: trafficResponse,
        responseLoading: trafficLoading,
        responseError: trafficError,
        responseErrorObject: trafficErrorObject,
        queryId: trafficQueryId,
    } = useValues(trafficLogic)
    const { loadData: loadTraffic } = useActions(trafficLogic)
    const needsTraffic = only === 'newVisitorShare'
    const loading =
        responseLoading ||
        (!response && !responseError) ||
        (needsTraffic && (trafficLoading || (!trafficResponse && !trafficError)))
    const labelFromKey = (key: string): React.ReactNode => (
        <span>
            {RETENTION_LABELS[key] ?? key}
            {retentionAcquisitionRange.clamped && (
                <span className="block text-xs font-normal text-secondary">Last 90 days of selected range</span>
            )}
        </span>
    )
    const visitors = (trafficResponse as WebOverviewQueryResponse | undefined)?.results?.find(
        (item) => item.key === 'visitors'
    )

    if (loading) {
        return (
            <>
                {Array.from({ length: only ? 1 : RETENTION_CARD_ORDER.length }, (_, index) => (
                    <MarketingMetricCard key={index} loading labelFromKey={labelFromKey} />
                ))}
            </>
        )
    }

    if (responseError || (needsTraffic && trafficError)) {
        const retentionFailed = !!responseError
        return (
            <div className="col-span-full">
                <MarketingQueryError
                    message="Couldn't load these metrics. Try again."
                    queryId={
                        retentionFailed
                            ? (responseErrorObject?.queryId ?? queryId)
                            : (trafficErrorObject?.queryId ?? trafficQueryId)
                    }
                    onRetry={() => (retentionFailed ? loadData : loadTraffic)('force_async')}
                    loading={loading}
                />
            </div>
        )
    }

    const totals = retentionTotals(response as MarketingAnalyticsRetentionQueryResponse | undefined)
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
        {
            kind: 'metric',
            item: {
                key: 'returners',
                kind: 'unit',
                value: totals.returners,
                previous: totals.previousReturners || undefined,
                changeFromPreviousPct: pctChange(totals.returners, totals.previousReturners || undefined),
            } as never,
        },
        newVisitorShareSpec(totals, visitors),
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

    // New visitor share belongs to Acquisition, so it is reachable by key but not part of the
    // section's own set.
    const byKey = new Map(specs.map((spec) => [spec.kind === 'metric' ? spec.item.key : spec.key, spec]))
    const shown = only
        ? [byKey.get(only)].filter((spec): spec is MetricCardSpec => !!spec)
        : RETENTION_CARD_ORDER.map((key) => byKey.get(key)).filter((spec): spec is MetricCardSpec => !!spec)

    return (
        <>
            {shown.map((spec) => (
                <MarketingMetricCard
                    key={spec.kind === 'metric' ? spec.item.key : spec.key}
                    spec={expandable(
                        spec.kind === 'notice' && retentionAcquisitionRange.clamped
                            ? {
                                  ...spec,
                                  message: `${spec.message} This metric covers the last 90 days of the selected range.`,
                              }
                            : spec
                    )}
                    loading={false}
                    labelFromKey={labelFromKey}
                />
            ))}
        </>
    )
}
