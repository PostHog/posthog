import { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { WebOverviewItem } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { MetricCardSpec, pctChange } from './cards/metricCardSpec'

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
