import { BAR_BAND_PADDING } from './chartMath'
import { bucketCount, isCompareSeries } from './chartSeries'
import type { BarLayout, ChartKind, ChartSeries } from './types'

const MIN_BAR_WIDTH = 6
const MIN_STACK_WIDTH = 14

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
