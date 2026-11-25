import { dayjs } from 'lib/dayjs'

import { CompareLabelType } from '~/types'

import type { AnomalyPoint } from 'products/alerts/frontend/types'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'
import type { AnomalyInsightSeriesApi } from 'products/signals/frontend/generated/api.schemas'

// Both strings are wall-clock times in the project timezone. A chart day has no offset and can lack the time.
function wallClock(value: string): string {
    const normalized = value.replace(' ', 'T').slice(0, 19)
    return normalized.length === 10 ? `${normalized}T00:00:00` : normalized
}

// Matches the label the scorer stores: a list breakdown is joined with `::`.
function breakdownLabel(value: IndexedTrendResult['breakdown_value']): string | null {
    if (value == null) {
        return null
    }
    return Array.isArray(value) ? value.join('::') : String(value)
}

/**
 * The chart series of a scored series, in the current period.
 *
 * The scorer identifies a series by a key the chart does not have, so a scored series is matched to a chart
 * series by label and breakdown value.
 */
export function findChartSeries(
    scored: Pick<AnomalyInsightSeriesApi, 'series_label' | 'breakdown_value'>,
    indexedResults: IndexedTrendResult[]
): IndexedTrendResult | undefined {
    return indexedResults.find(
        (candidate) =>
            candidate.compare_label !== CompareLabelType.Previous &&
            (candidate.label ?? '') === (scored.series_label ?? '') &&
            breakdownLabel(candidate.breakdown_value) === scored.breakdown_value
    )
}

/**
 * The flagged buckets of an insight as chart anomaly points. A flagged bucket outside the days of the chart is left out.
 */
export function buildAnomalyScorePoints(
    scoredSeries: AnomalyInsightSeriesApi[],
    indexedResults: IndexedTrendResult[]
): AnomalyPoint[] {
    const points: AnomalyPoint[] = []
    for (const scored of scoredSeries) {
        const result = findChartSeries(scored, indexedResults)
        if (!result) {
            continue
        }
        const days = result.days ?? []
        const dayIndexByWallClock = new Map(days.map((day, index) => [wallClock(day), index]))
        for (const bucket of scored.buckets) {
            if (!bucket.flag) {
                continue
            }
            const index = dayIndexByWallClock.get(wallClock(bucket.bucket_start))
            if (index !== undefined) {
                points.push({ index, date: days[index], score: bucket.score, seriesIndex: result.seriesIndex })
            }
        }
    }
    return points
}

/**
 * The chart series to show alone for the series of an Anomalies tab link. Null when the chart has no match, has one
 * series only, or already shows only that series, because a toggle in that state shows the others again.
 */
export function seriesToIsolate(
    scoredSeries: AnomalyInsightSeriesApi[],
    seriesKey: string,
    indexedResults: IndexedTrendResult[],
    isHidden: (result: IndexedTrendResult) => boolean
): IndexedTrendResult | null {
    const scored = scoredSeries.find((candidate) => candidate.series_key === seriesKey)
    const result = scored && findChartSeries(scored, indexedResults)
    if (!result) {
        return null
    }
    const others = indexedResults.filter(
        (candidate) => candidate.compare_label !== CompareLabelType.Previous && candidate !== result
    )
    if (others.length === 0 || (!isHidden(result) && others.every(isHidden))) {
        return null
    }
    return result
}

/** Groups indices into inclusive `[start, end]` runs of neighbours, so adjacent buckets shade as one band. */
export function contiguousRuns(indices: number[]): [number, number][] {
    const sorted = [...new Set(indices)].sort((a, b) => a - b)
    const runs: [number, number][] = []
    for (const index of sorted) {
        const last = runs[runs.length - 1]
        if (last && index === last[1] + 1) {
            last[1] = index
        } else {
            runs.push([index, index])
        }
    }
    return runs
}

// The anomaly history endpoint rejects a range longer than a year, and a monthly chart can show more.
const MAX_HISTORY_DAYS = 365

/** The chart range as the history request takes it. A longer chart keeps its newest year, where the flags are. */
export function scoreHistoryRange(
    dateFrom?: string | null,
    dateTo?: string | null
): { date_from?: string; date_to?: string } {
    if (!dateFrom || !dateTo) {
        return { ...(dateFrom && { date_from: dateFrom }), ...(dateTo && { date_to: dateTo }) }
    }
    const earliest = dayjs(dateTo).subtract(MAX_HISTORY_DAYS, 'day')
    return { date_from: dayjs(dateFrom).isBefore(earliest) ? earliest.toISOString() : dateFrom, date_to: dateTo }
}
