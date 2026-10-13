import { BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { TrendResult } from '~/types'

import type { ComparedValue } from './breakdownTableColumn'

export interface ConversionValueByBreakdown {
    total?: ComparedValue
    average?: ComparedValue
}

/** Series order in `conversionValueSeries`. */
const TOTAL_ORDER = 0
const AVERAGE_ORDER = 1

const seriesOrder = (result: TrendResult): number => result.order ?? result.action?.order ?? 0

/** Trends reports an untagged visit as its own sentinel, while the stats table reports SQL NULL,
 * which `webStatsRows` reads as an empty string. Both have to land on the same key or the two
 * halves of a row never meet. */
const joinKey = (breakdownValue: TrendResult['breakdown_value']): string => {
    const value = String(breakdownValue ?? '')
    return value === BREAKDOWN_NULL_STRING_LABEL ? '' : value
}

const pair = (current: number | undefined, previous: number | undefined): ComparedValue | undefined =>
    current === undefined ? undefined : [current, previous ?? null]

/** Keyed by the raw breakdown value, not its display label. */
export function conversionValueRows(results: TrendResult[] | undefined): Map<string, ConversionValueByBreakdown> {
    const byKey = new Map<string, ConversionValueByBreakdown>()

    for (const order of [TOTAL_ORDER, AVERAGE_ORDER]) {
        const rows = (results ?? []).filter(
            // The fold row is an aggregate over values the stats table lists individually, so
            // merging it would attribute the whole tail to one row.
            (result) => seriesOrder(result) === order && result.breakdown_value !== BREAKDOWN_OTHER_STRING_LABEL
        )
        const current = rows.filter((result) => result.compare_label !== 'previous')
        const previous = new Map(
            rows.filter((result) => result.compare_label === 'previous').map((r) => [joinKey(r.breakdown_value), r])
        )

        for (const row of current) {
            const key = joinKey(row.breakdown_value)
            const value = pair(row.aggregated_value, previous.get(key)?.aggregated_value)
            if (value === undefined) {
                continue
            }
            const existing = byKey.get(key) ?? {}
            byKey.set(key, order === TOTAL_ORDER ? { ...existing, total: value } : { ...existing, average: value })
        }
    }

    return byKey
}
