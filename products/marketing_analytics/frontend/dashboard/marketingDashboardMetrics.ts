import { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { MarketingAnalyticsRetentionSummaryRow, WebOverviewItem } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { MetricCardSpec, pctChange } from './cards/metricCardSpec'

export interface RetentionTotals {
    acquired: number
    previousAcquired: number
    returners: number
    previousReturners: number
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
    returners: 0,
    previousReturners: 0,
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
            totals.previousReturners += row.returners
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
        totals.returners += row.returners
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

/** One series of a multi-series trends response, picked by the order the query asked for it in.
 * `value` is undefined when that series returned nothing, which the caller shows as N/A rather
 * than as a zero it cannot stand behind. */
export function seriesTotal(results: TrendResult[] | undefined, order: number): { value?: number; previous?: number } {
    const matching = (results ?? []).filter((result) => (result.order ?? result.action?.order ?? 0) === order)
    if (!matching.length) {
        return {}
    }
    const current = matching.find((result) => result.compare_label !== 'previous')
    const previous = matching.find((result) => result.compare_label === 'previous')
    return {
        value: current?.aggregated_value,
        previous: previous?.aggregated_value,
    }
}

/** One overview scalar divided by another, as a card. Null when the denominator is missing or
 * zero, which the caller shows as a notice rather than as a misleading zero. */
export function ratioItem(
    results: WebOverviewItem[] | undefined,
    key: string,
    numeratorKey: string,
    denominatorKey: string
): MetricCardSpec | null {
    const numerator = results?.find((item) => item.key === numeratorKey)
    const denominator = results?.find((item) => item.key === denominatorKey)
    if (numerator?.value === undefined || !denominator?.value) {
        return null
    }
    const value = numerator.value / denominator.value
    const previous =
        numerator.previous !== undefined && denominator.previous ? numerator.previous / denominator.previous : undefined
    return {
        kind: 'metric',
        item: {
            key,
            kind: 'unit',
            value,
            previous,
            changeFromPreviousPct: pctChange(value, previous),
        } as OverviewMetricCardItem,
    }
}
