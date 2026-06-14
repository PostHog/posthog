import type { Series, SlopeSeriesMeta } from '@posthog/quill-charts'

export interface SlopeResultLike {
    id?: string | number
    label?: string | null
    data: number[]
}

export interface BuildSlopeSeriesOpts<R extends SlopeResultLike> {
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
}

/** One slope line per result — its first and last value `[start, end]`. Series hidden via the
 *  legend, or with fewer than two points (a slope needs both ends), are dropped. Colors come from
 *  the original index so dropping a series doesn't shift the palette of the rest. */
export function buildSlopeSeries<R extends SlopeResultLike>(
    results: R[],
    opts: BuildSlopeSeriesOpts<R>
): Series<SlopeSeriesMeta>[] {
    const series: Series<SlopeSeriesMeta>[] = []
    results.forEach((r, index) => {
        if (opts.getHidden?.(r, index)) {
            return
        }
        const data = r.data ?? []
        if (data.length < 2) {
            return
        }
        series.push({
            key: String(r.id ?? index),
            label: r.label ?? '',
            color: opts.getColor(r, index),
            data: [data[0], data[data.length - 1]],
        })
    })
    return series
}

/** The two columns of the slope graph — the first and last x-axis labels. */
export function slopeLabels(labels: string[]): string[] {
    if (labels.length < 2) {
        return labels
    }
    return [labels[0], labels[labels.length - 1]]
}
