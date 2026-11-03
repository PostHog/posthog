import type { Theme } from '@/ui/theme'

import { formatAxisDate, formatChange, formatClockTime, formatTooltipDate } from './chartMath'
import type { ChartInterval, ChartSeries, ChartTooltipPoint, ChartTooltipRow, MetricChartProps } from './types'

/** The tooltip shows this many series rows, then "+N more". Full screen shows them all. */
export const TOOLTIP_MAX_ROWS = 4

/** The key of the one series a `points` chart draws. */
export const SINGLE_SERIES_KEY = 'value'

/** A `points` chart draws its one series in the theme's color for its accent. */
export function chartSeriesOf(props: MetricChartProps, theme: Theme): ChartSeries[] {
    if (props.series) {
        return props.series
    }
    return [
        { key: SINGLE_SERIES_KEY, label: props.label, color: theme.accentColor[props.accent], points: props.points },
    ]
}

export function isCompareSeries(series: ChartSeries): boolean {
    return series.compareOf !== undefined
}

export function seriesStroke(series: ChartSeries, theme: Theme): { color: string; dotted: boolean } {
    const compare = isCompareSeries(series)
    return {
        color: compare ? theme.previousPeriodColor : series.color,
        dotted: (series.style ?? (compare ? 'dotted' : 'solid')) === 'dotted',
    }
}

export function bucketCount(series: readonly ChartSeries[]): number {
    return Math.max(0, ...series.map((s) => s.points.length))
}

/** The bucket dates for the x axis and the tooltip header, from the first current series. */
export function bucketDates(series: readonly ChartSeries[]): number[] {
    const primary = series.find((s) => !isCompareSeries(s)) ?? series[0]
    return primary ? primary.points.map((point) => point.at) : []
}

export function visibleSeries(series: readonly ChartSeries[], hiddenKeys: readonly string[]): ChartSeries[] {
    return series.filter((s) => !hiddenKeys.includes(s.key))
}

/**
 * 0 where any visible series has a value and NaN where none does, so `snapToValue` moves a touch off buckets that
 * would show an empty tooltip.
 */
export function selectableMask(visible: readonly ChartSeries[], count: number): number[] {
    const mask: number[] = []
    for (let index = 0; index < count; index++) {
        mask.push(visible.some((s) => Number.isFinite(s.points[index]?.value)) ? 0 : Number.NaN)
    }
    return mask
}

/** True when any current series marks bucket `index` as still in progress. */
export function isIncompleteBucket(series: readonly ChartSeries[], index: number): boolean {
    return series.some((s) => !isCompareSeries(s) && s.incompleteFrom !== undefined && index >= s.incompleteFrom)
}

/** The visible current series at one bucket, highest first, each with its previous period when there is one. */
export function tooltipPoint(
    series: readonly ChartSeries[],
    hiddenKeys: readonly string[],
    index: number,
    interval: ChartInterval
): ChartTooltipPoint | null {
    const at = bucketDates(series)[index]
    if (at === undefined) {
        return null
    }
    const rows: ChartTooltipRow[] = []
    for (const s of visibleSeries(series, hiddenKeys)) {
        const value = s.points[index]?.value
        if (isCompareSeries(s) || value === undefined || !Number.isFinite(value)) {
            continue
        }
        const compare = series.find((other) => other.compareOf === s.key)?.points[index]
        rows.push({
            key: s.key,
            label: s.label,
            color: s.color,
            value,
            ...(compare && Number.isFinite(compare.value)
                ? { previous: { value: compare.value, at: compare.at } }
                : {}),
        })
    }
    if (rows.length === 0) {
        return null
    }
    rows.sort((a, b) => b.value - a.value)
    return { index, at, interval, rows, incomplete: isIncompleteBucket(series, index) }
}

export interface TooltipContent {
    header: string
    rows: ChartTooltipRow[]
    /** Rows left out after `maxRows`. */
    more: number
    /** "Previous: 1,071 (Sep 30)" and "+133 (+12.4%)", only when one series shows and it has a previous period. */
    compare: { previous: string; change: string } | null
    /** "In progress. Data until 14:32." for a bucket that is still filling. */
    note: string | null
}

export interface TooltipFormat {
    formatValue: (value: number) => string
    compact: boolean
    maxRows: number
    dataUntil?: number
}

export function tooltipContent(point: ChartTooltipPoint, format: TooltipFormat): TooltipContent {
    const { formatValue, compact, maxRows, dataUntil } = format
    const only = point.rows.length === 1 ? point.rows[0] : undefined
    const previous = only?.previous
    return {
        header: formatTooltipDate(point.at, point.interval, compact),
        rows: point.rows.slice(0, maxRows),
        more: Math.max(0, point.rows.length - maxRows),
        compare:
            only && previous
                ? {
                      previous: `Previous: ${formatValue(previous.value)} (${formatAxisDate(previous.at, point.interval)})`,
                      change: formatChange(only.value, previous.value, formatValue),
                  }
                : null,
        note: point.incomplete
            ? dataUntil === undefined
                ? 'In progress.'
                : `In progress. Data until ${formatClockTime(dataUntil)}.`
            : null,
    }
}

export interface RangeRow {
    key: string
    label: string
    color: string
    /** "1,071 → 1,204" */
    values: string
    change: string
}

export interface RangeContent {
    /** "Oct 1 → Oct 14" */
    header: string
    rows: RangeRow[]
}

/** The two-finger result: the earlier marker first, then each visible current series' change between them. */
export function rangeContent(
    series: readonly ChartSeries[],
    hiddenKeys: readonly string[],
    a: number,
    b: number,
    interval: ChartInterval,
    formatValue: (value: number) => string
): RangeContent | null {
    const dates = bucketDates(series)
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    const from = dates[lo]
    const to = dates[hi]
    if (from === undefined || to === undefined) {
        return null
    }
    const rows: RangeRow[] = []
    for (const s of visibleSeries(series, hiddenKeys)) {
        const start = s.points[lo]?.value
        const end = s.points[hi]?.value
        if (isCompareSeries(s) || start === undefined || end === undefined) {
            continue
        }
        if (!Number.isFinite(start) || !Number.isFinite(end)) {
            continue
        }
        rows.push({
            key: s.key,
            label: s.label,
            color: s.color,
            values: `${formatValue(start)} → ${formatValue(end)}`,
            change: formatChange(end, start, formatValue),
        })
    }
    const header = `${formatAxisDate(from, interval)} → ${formatAxisDate(to, interval)}`
    return { header, rows }
}
