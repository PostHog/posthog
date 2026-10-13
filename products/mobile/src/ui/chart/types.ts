import type { Accent } from '@/model/types'

export type ChartKind = 'line' | 'bar'

export type ChartInterval = 'hour' | 'day' | 'week' | 'month'

/** `at` is epoch milliseconds (victory-native's press state misbehaves with Date objects, issue #591). `value` NaN = gap. */
export interface ChartPoint {
    at: number
    value: number
}

export interface MetricChartProps {
    points: ChartPoint[]
    kind: ChartKind
    interval: ChartInterval
    accent: Accent
    /** Tooltip row label, usually the metric title. */
    label: string
    formatValue: (value: number) => string
    /** Defaults to 144, the web chart's `h-36`. */
    height?: number
    /**
     * Called with the point under the finger each time it changes, and with `null` when the finger lifts (a tap
     * reports its point, then `null`) or the data changes. The chart keeps showing the last selection after release.
     */
    onSelect?: (point: ChartPoint | null) => void
    testID?: string
}
