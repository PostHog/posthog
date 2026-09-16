import { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { MarketingAnalyticsRetentionSummaryRow, WebOverviewItem } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { MetricCardSpec, pctChange } from './cards/metricCardSpec'

export interface RetentionTotals {
    acquired: number
    previousAcquired: number
    eligible7d: number
    returned7d: number
    previousEligible7d: number
    previousReturned7d: number
    eligible30d: number
    returned30d: number
    previousEligible30d: number
    previousReturned30d: number
    /** Returners-weighted mean of the per-row medians, or null when nobody has returned. */
    medianReturnDays: number | null
    previousMedianReturnDays: number | null
}

const EMPTY_TOTALS: RetentionTotals = {
    acquired: 0,
    previousAcquired: 0,
    eligible7d: 0,
    returned7d: 0,
    previousEligible7d: 0,
    previousReturned7d: 0,
    eligible30d: 0,
    returned30d: 0,
    previousEligible30d: 0,
    previousReturned30d: 0,
    medianReturnDays: null,
    previousMedianReturnDays: null,
}

/** The summary is per breakdown value, so a project-wide number is the sum of its rows. */
export function retentionTotals(rows: MarketingAnalyticsRetentionSummaryRow[] | undefined): RetentionTotals {
    if (!rows?.length) {
        return EMPTY_TOTALS
    }
    const totals = { ...EMPTY_TOTALS }
    let weightedDays = 0
    let weight = 0
    let previousWeightedDays = 0
    let previousWeight = 0

    for (const row of rows) {
        if (row.previous) {
            totals.previousAcquired += row.acquired
            totals.previousEligible7d += row.eligible7d
            totals.previousReturned7d += row.returned7d
            totals.previousEligible30d += row.eligible30d
            totals.previousReturned30d += row.returned30d
            if (row.medianReturnDays !== null && row.returners) {
                previousWeightedDays += row.medianReturnDays * row.returners
                previousWeight += row.returners
            }
            continue
        }
        totals.acquired += row.acquired
        totals.eligible7d += row.eligible7d
        totals.returned7d += row.returned7d
        totals.eligible30d += row.eligible30d
        totals.returned30d += row.returned30d
        if (row.medianReturnDays !== null && row.returners) {
            weightedDays += row.medianReturnDays * row.returners
            weight += row.returners
        }
    }

    totals.medianReturnDays = weight ? weightedDays / weight : null
    totals.previousMedianReturnDays = previousWeight ? previousWeightedDays / previousWeight : null
    return totals
}

/** Sums a BoldNumber trends response, keeping the two compared periods apart. */
export function sumTrendSeries(results: TrendResult[] | undefined): { value: number; previous: number | undefined } {
    if (!results?.length) {
        return { value: 0, previous: undefined }
    }
    let value = 0
    let previous: number | undefined
    for (const result of results) {
        const amount = result.aggregated_value ?? 0
        if (result.compare_label === 'previous') {
            previous = (previous ?? 0) + amount
            continue
        }
        value += amount
    }
    return { value, previous }
}

/** Pageviews over sessions, for the row and for the period before it. */
export function pagesPerSessionItem(results: WebOverviewItem[] | undefined): MetricCardSpec | null {
    const views = results?.find((item) => item.key === 'views')
    const sessions = results?.find((item) => item.key === 'sessions')
    if (!views?.value || !sessions?.value) {
        return null
    }
    const value = views.value / sessions.value
    const previous = views.previous !== undefined && sessions.previous ? views.previous / sessions.previous : undefined
    return {
        kind: 'metric',
        item: {
            key: 'pages_per_session',
            kind: 'unit',
            value,
            previous,
            changeFromPreviousPct: pctChange(value, previous),
        } as OverviewMetricCardItem,
    }
}
