import { BAR_BAND_PADDING, BAR_MIN_HEIGHT } from './chartMath'
import { bucketCount, isCompareSeries } from './chartSeries'
import type { BarLayout, ChartKind, ChartSeries } from './types'

const MIN_BAR_WIDTH = 6
const MIN_STACK_WIDTH = 14
/** The narrow bars of a small chart leave more of each slot empty than the full chart does. */
const SPARK_BAR_SHARE = 0.64
/** A small chart never scales to a peak below this, so a bucket with 1 occurrence draws short, not at full height. */
const SPARK_BAR_FLOOR = 10

export interface SparkBar {
    /** Left edge and width in percent of the chart width, so the bars fill any width without a layout pass. */
    x: number
    width: number
    height: number
    highlighted: boolean
}

/** Zero-based bars that each chart scales to its own peak. A zero, negative or missing value draws no bar. */
export function sparkBars(values: readonly number[], height: number, highlightFrom: number | null): SparkBar[] {
    const counts = values.map((value) => (Number.isFinite(value) ? Math.max(0, value) : 0))
    const max = Math.max(SPARK_BAR_FLOOR, ...counts)
    const pitch = 100 / Math.max(1, counts.length)
    const width = pitch * SPARK_BAR_SHARE
    return counts.flatMap((value, index) =>
        value > 0
            ? [
                  {
                      x: index * pitch + (pitch - width) / 2,
                      width,
                      height: Math.min(height, Math.max(BAR_MIN_HEIGHT, Math.round((value / max) * height))),
                      highlighted: highlightFrom !== null && index >= highlightFrom,
                  },
              ]
            : []
    )
}

export function barPageSize(plotWidth: number, seriesCount: number, layout: BarLayout): number {
    const groupWidth = layout === 'stacked' ? MIN_STACK_WIDTH : MIN_BAR_WIDTH * Math.max(1, seriesCount)
    return Math.max(1, Math.floor((plotWidth * (1 - BAR_BAND_PADDING)) / groupWidth))
}

export function barWindow(count: number, size: number, endOffset: number): { start: number; end: number } {
    const end = Math.max(1, count - Math.max(0, endOffset))
    return { start: Math.max(0, end - size), end: Math.min(count, end) }
}

export function barSegments(
    series: ChartSeries[],
    layout: BarLayout,
    kind: ChartKind = 'bar'
): { starts: number[]; ends: number[] }[] {
    const totalsByAxis = {
        left: {
            positive: Array<number>(bucketCount(series)).fill(0),
            negative: Array<number>(bucketCount(series)).fill(0),
        },
        right: {
            positive: Array<number>(bucketCount(series)).fill(0),
            negative: Array<number>(bucketCount(series)).fill(0),
        },
    }
    return series.map((s) => {
        const starts: number[] = []
        const ends: number[] = []
        const axis = totalsByAxis[s.axis ?? 'left']
        const bar = (s.kind ?? kind) === 'bar' && !isCompareSeries(s)
        s.points.forEach((point, index) => {
            const totals = point.value < 0 ? axis.negative : axis.positive
            const start = layout === 'stacked' && bar ? (totals[index] ?? 0) : 0
            starts.push(start)
            ends.push(Number.isFinite(point.value) ? start + point.value : Number.NaN)
            if (Number.isFinite(point.value) && bar) {
                totals[index] = start + point.value
            }
        })
        return { starts, ends }
    })
}
