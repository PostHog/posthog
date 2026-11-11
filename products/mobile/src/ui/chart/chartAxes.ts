import { barSegments } from './barLayout'
import { isCompareSeries } from './chartSeries'
import type { BarLayout, ChartKind, ChartSeries } from './types'

export interface ChartAxisData {
    values: number[]
    kind: ChartKind
    formatValue: (value: number) => string
    startAtZero?: boolean
}

/** Each axis fits its own units; lines never contribute to a bar stack. */
export function chartAxes(
    series: ChartSeries[],
    kind: ChartKind,
    layout: BarLayout,
    formatValue: (value: number) => string
): { left: ChartAxisData; right?: ChartAxisData } {
    const segments = barSegments(series, layout, kind)
    const axis = (side: 'left' | 'right'): ChartAxisData => {
        const members = series.filter((s) => (s.axis ?? 'left') === side)
        const bars = members.some((s) => (s.kind ?? kind) === 'bar')
        return {
            kind: bars ? 'bar' : 'line',
            formatValue: members[0]?.formatValue ?? formatValue,
            startAtZero: members.some((s) => s.startAtZero),
            values: series.flatMap((s, index) => {
                if ((s.axis ?? 'left') !== side) {
                    return []
                }
                return (s.kind ?? kind) === 'bar'
                    ? isCompareSeries(s)
                        ? []
                        : [...(segments[index]?.starts ?? []), ...(segments[index]?.ends ?? [])]
                    : s.points.map((p) => p.value)
            }),
        }
    }
    return { left: axis('left'), ...(series.some((s) => s.axis === 'right') ? { right: axis('right') } : {}) }
}
