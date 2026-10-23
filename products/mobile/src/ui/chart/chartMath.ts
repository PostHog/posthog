import { formatMonthDay, weekdayName } from '@/lib/dates'

import type { ChartInterval, ChartKind, ChartPoint } from './types'

export const CHART_DEFAULT_HEIGHT = 144
export const TICK_FONT_SIZE = 11
/** Space between the y tick labels and the plot, and the smallest space between two x tick labels. */
export const TICK_GAP = 8
/** Fraction of each bar's slot left empty, as in the web chart. */
export const BAR_BAND_PADDING = 0.25
/** The shortest nonzero bar. */
export const BAR_MIN_HEIGHT = 2

// Menlo, Android's monospace and SF Mono all advance 0.6em per glyph, so label widths are known without measuring.
const MONO_ADVANCE_EM = 0.6
const Y_TICK_TARGET = 4
const X_TICK_MAX = 4
const LINE_PADDING_RATIO = 0.05

export function samePoints(a: readonly ChartPoint[], b: readonly ChartPoint[]): boolean {
    if (a === b) {
        return true
    }
    return a.length === b.length && a.every((p, i) => Object.is(p.at, b[i]?.at) && Object.is(p.value, b[i]?.value))
}

export function monoTextWidth(text: string, fontSize: number = TICK_FONT_SIZE): number {
    return Math.ceil(text.length * fontSize * MONO_ADVANCE_EM)
}

export function niceStep(raw: number): number {
    if (!(raw > 0) || !Number.isFinite(raw)) {
        return 1
    }
    const magnitude = 10 ** Math.floor(Math.log10(raw))
    const fraction = raw / magnitude
    const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10
    return nice * magnitude
}

export interface YAxisTicks {
    domain: [number, number]
    ticks: number[]
}

// Removes float noise such as 0.30000000000000004, so labels and gridlines land on the intended values.
function clean(value: number): number {
    return Number.parseFloat(value.toPrecision(12))
}

function ticksBetween(lo: number, hi: number, step: number): number[] {
    const ticks: number[] = []
    const count = Math.round((hi - lo) / step)
    for (let i = 0; i <= count; i++) {
        ticks.push(clean(lo + i * step))
    }
    return ticks
}

/**
 * Bars start at zero and count whole things, so their step is never below 1. Lines float to the data with a little
 * padding, but do not cross zero when every value is positive.
 */
export function yAxisTicks(values: number[], kind: ChartKind, target: number = Y_TICK_TARGET): YAxisTicks {
    const finite = values.filter(Number.isFinite)
    const segments = Math.max(1, target - 1)
    if (kind === 'bar') {
        const max = Math.max(0, ...finite)
        const min = Math.min(0, ...finite)
        const step = Math.max(1, niceStep((max - min) / segments))
        const lo = Math.floor(min / step) * step
        const hi = Math.max(step, Math.ceil(max / step) * step)
        return { domain: [lo, hi], ticks: ticksBetween(lo, hi, step) }
    }
    if (finite.length === 0) {
        return { domain: [0, 1], ticks: [0, 1] }
    }
    const min = Math.min(...finite)
    const max = Math.max(...finite)
    const span = max - min
    const pad = span > 0 ? span * LINE_PADDING_RATIO : Math.abs(max) * 0.1 || 1
    let low = min - pad
    const high = max + pad
    if (min >= 0 && low < 0) {
        low = 0
    }
    const step = niceStep((high - low) / segments)
    const lo = clean(Math.floor(low / step) * step)
    const hi = clean(Math.ceil(high / step) * step)
    return { domain: [lo, hi], ticks: ticksBetween(lo, hi, step) }
}

/**
 * Picks up to four evenly spread point indices for x labels. The count drops until labels of `labelWidth` fit in
 * `plotWidth` with a gap between them, even after the edge labels shift inward to stay on screen.
 */
export function xTickIndices(count: number, plotWidth: number, labelWidth: number, max: number = X_TICK_MAX): number[] {
    if (count <= 0) {
        return []
    }
    const fit = Math.floor((plotWidth + TICK_GAP) / (labelWidth + TICK_GAP))
    const ticks = Math.min(max, count, Math.max(1, fit))
    if (ticks === 1) {
        return [0]
    }
    const indices = new Set<number>()
    for (let i = 0; i < ticks; i++) {
        indices.add(Math.round((i * (count - 1)) / (ticks - 1)))
    }
    return [...indices]
}

export function nearestIndex(xs: readonly number[], x: number): number {
    'worklet'
    let best = -1
    let bestDistance = Number.POSITIVE_INFINITY
    for (let i = 0; i < xs.length; i++) {
        const candidate = xs[i]
        if (candidate === undefined || !Number.isFinite(candidate)) {
            continue
        }
        const distance = Math.abs(candidate - x)
        if (distance < bestDistance) {
            best = i
            bestDistance = distance
        }
    }
    return best
}

export function snapToValue(values: readonly number[], index: number): number {
    'worklet'
    if (index < 0 || values.length === 0) {
        return -1
    }
    for (let offset = 0; offset < values.length; offset++) {
        const before = values[index - offset]
        if (before !== undefined && Number.isFinite(before)) {
            return index - offset
        }
        const after = values[index + offset]
        if (after !== undefined && Number.isFinite(after)) {
            return index + offset
        }
    }
    return -1
}

export function tooltipLeft(anchorX: number, tooltipWidth: number, containerWidth: number, gap: number): number {
    const maxLeft = Math.max(0, containerWidth - tooltipWidth)
    const right = anchorX + gap
    const left = right + tooltipWidth <= containerWidth ? right : anchorX - gap - tooltipWidth
    return Math.min(maxLeft, Math.max(0, left))
}

function pad2(value: number): string {
    return String(value).padStart(2, '0')
}

function clock24(date: Date): string {
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

function monthYear(date: Date): string {
    const [month] = formatMonthDay(date).split(' ')
    return `${month} ${date.getFullYear()}`
}

export function formatAxisDate(at: number, interval: ChartInterval): string {
    const date = new Date(at)
    switch (interval) {
        case 'hour':
            return clock24(date)
        case 'day':
        case 'week':
            return formatMonthDay(date)
        case 'month':
            return monthYear(date)
    }
}

const MINUS = '−'

function weekEnd(start: Date): Date {
    const end = new Date(start)
    end.setDate(end.getDate() + 6)
    return end
}

// "Oct 6 – 12", "Sep 29 – Oct 5", or with both years when the week crosses one. The en dash is the web's date range
// separator (frontend/src/lib/utils/datetime.ts).
function weekSpan(start: Date, withYear: boolean): string {
    const end = weekEnd(start)
    if (start.getFullYear() !== end.getFullYear()) {
        return `${formatMonthDay(start)}, ${start.getFullYear()} – ${formatMonthDay(end)}, ${end.getFullYear()}`
    }
    const year = withYear ? `, ${end.getFullYear()}` : ''
    if (start.getMonth() === end.getMonth()) {
        return `${formatMonthDay(start)} – ${end.getDate()}${year}`
    }
    return `${formatMonthDay(start)} – ${formatMonthDay(end)}${year}`
}

/** The tooltip's bucket header. `compact` drops the year, for the small charts in a pin. */
export function formatTooltipDate(at: number, interval: ChartInterval, compact = false): string {
    const date = new Date(at)
    switch (interval) {
        case 'hour':
            return compact ? clock24(date) : `${weekdayName(date)}, ${formatMonthDay(date)}, ${clock24(date)}`
        case 'day':
            return compact
                ? `${weekdayName(date)}, ${formatMonthDay(date)}`
                : `${weekdayName(date)}, ${formatMonthDay(date)}, ${date.getFullYear()}`
        case 'week':
            return weekSpan(date, !compact)
        case 'month':
            return monthYear(date)
    }
}

export function formatClockTime(at: number): string {
    return clock24(new Date(at))
}

/**
 * "+133 (+12.4%)", "−133 (−12.4%)" or "No change". The percent is left out when the previous value is 0. The sign
 * carries the direction, because the app does not know whether up is good for a metric.
 */
export function formatChange(value: number, previous: number, formatValue: (value: number) => string): string {
    const diff = value - previous
    if (diff === 0 || !Number.isFinite(diff)) {
        return 'No change'
    }
    const sign = diff > 0 ? '+' : MINUS
    const absolute = `${sign}${formatValue(Math.abs(diff))}`
    if (previous === 0) {
        return absolute
    }
    return `${absolute} (${sign}${Math.abs((diff / previous) * 100).toFixed(1)}%)`
}
