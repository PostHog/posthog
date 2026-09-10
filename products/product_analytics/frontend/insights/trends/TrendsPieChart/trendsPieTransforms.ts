import { defaultSliceValue } from '@posthog/quill-charts'
import type { ResolvedSeries, Series } from '@posthog/quill-charts'

import type { IndexedTrendResult } from 'scenes/trends/types'

import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'
import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'

export interface BuildTrendsPieSeriesOpts<R> {
    /** Resolved color per result (typically `getTrendsColor`). */
    getColor: (r: R, index: number) => string
    /** True when the result should be excluded from rendering. */
    getHidden?: (r: R, index: number) => boolean
    /** Optional label override per result — used to format breakdown values. */
    getLabel?: (r: R) => string
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
        const label = opts.getLabel ? opts.getLabel(r) : humanizeSeriesLabel(r.label)
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
                action: r.action ?? undefined,
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

/** Total of the magnitudes the pie really draws — for the headline aggregate, the donut center,
 *  and the share-of-total percentages beside the slices. `computePieLayout` skips an excluded
 *  series and clamps a negative or non-finite magnitude to 0, so a total summed straight off
 *  `aggregated_value` drifts away from the slices as soon as one series is negative, and the
 *  shares stop adding up to 100%. */
export function sumTrendsPieSeries<Meta>(series: Series<Meta>[], hiddenKeys: readonly string[] = []): number {
    const hidden = new Set(hiddenKeys)
    let total = 0
    for (const s of series) {
        if (s.visibility?.excluded || hidden.has(s.key)) {
            continue
        }
        // `defaultSliceValue` reads `data` only, so the resolved color it asks for is irrelevant here.
        const value = defaultSliceValue(s as ResolvedSeries<Meta>)
        if (Number.isFinite(value) && value > 0) {
            total += value
        }
    }
    return total
}
