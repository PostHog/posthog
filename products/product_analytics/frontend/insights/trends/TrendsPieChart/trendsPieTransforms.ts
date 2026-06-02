import type { Series } from 'lib/hog-charts'
import type { IndexedTrendResult } from 'scenes/trends/types'

import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'

export interface BuildTrendsPieSeriesOpts<R> {
    /** Resolved color per result (typically `getTrendsColor`). */
    getColor: (r: R, index: number) => string
    /** True when the result should be excluded from rendering. */
    getHidden?: (r: R, index: number) => boolean
    /** Optional label override per result — used to format breakdown values. */
    getLabel?: (r: R, index: number) => string
}

/** Maps the kea-side `IndexedTrendResult` list to hog-charts `Series<TrendsSeriesMeta>[]`,
 *  one slice per result. The pie chart consumes each series's first `data` entry as the slice
 *  magnitude via the default `sliceValue` resolver — see `PieChart`'s `sliceValue` config to
 *  override when the input data isn't already aggregated to a single value (the Trends adapter
 *  hits this path because `aggregated_value` is stored as `data[0]`). */
export function buildTrendsPieSeries<R extends IndexedTrendResult>(
    results: R[],
    opts: BuildTrendsPieSeriesOpts<R>
): Series<TrendsSeriesMeta>[] {
    return results.map((r, index) => {
        const excluded = opts.getHidden ? opts.getHidden(r, index) : false
        const label = opts.getLabel ? opts.getLabel(r, index) : (r.label ?? '')
        return {
            // Match the line/bar adapters — keying by `${r.id}` lets the click handler resolve
            // back to the source IndexedTrendResult without stashing it on meta.
            key: String(r.id),
            label,
            // Pie consumes `data[0]` as the magnitude (`aggregated_value` is the only numeric
            // value Trends carries for pie). Wrapped in an array because `Series.data` is a list.
            data: [r.aggregated_value ?? 0],
            color: opts.getColor(r, index),
            meta: {
                action: r.action,
                breakdown_value: r.breakdown_value,
                compare_label: r.compare_label,
                days: r.days,
                order: r.action?.order ?? r.id,
                filter: r.filter,
            },
            visibility: excluded ? { excluded: true } : undefined,
        }
    })
}
