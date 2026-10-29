import type { IntervalType } from '~/types'

import { dateLabel } from 'products/product_analytics/mcp/apps/explainChart/storyFacts'

export type ChartMomentKind = 'peak' | 'dip' | 'shift'

export interface ChartMoment {
    id: string
    kind: ChartMomentKind
    /** The points the moment covers, as an inclusive index range. */
    range: [number, number]
    /** Whether the moment is a rise or a fall, for the search for its cause. */
    direction: 'up' | 'down'
    title: string
}

export interface MomentSeries {
    data: number[]
    days: string[]
}

export interface MomentOptions {
    interval: IntervalType
    incompletePoints: number
}

const MAX_PEAKS = 2
// ponytail: the change-of-level search sorts both sides at every split, so it is O(n² log n). Above this many points
// it is skipped; an incremental median would lift the limit.
const MAX_SHIFT_POINTS = 400
const MIN_POINTS = 5
/** A series with this share of empty points is compared with its active points only. */
const SPARSE_SHARE = 0.3

interface Baseline {
    typical: number
    spread: number
    sparse: boolean
}

function mean(values: number[]): number {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

function median(values: number[]): number {
    if (!values.length) {
        return 0
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function spreadOf(values: number[], center: number): number {
    // The median distance from the center, scaled to match a standard deviation. One extreme point does not move it.
    const robust = median(values.map((value) => Math.abs(value - center))) * 1.4826
    if (robust > 0) {
        return robust
    }
    const average = mean(values)
    return Math.sqrt(mean(values.map((value) => (value - average) ** 2)))
}

function baselineOf(values: number[]): Baseline {
    const active = values.filter((value) => value > 0)
    const sparse = active.length > 0 && values.length - active.length >= values.length * SPARSE_SHARE
    const pool = sparse ? active : values
    const typical = median(pool)
    return { typical, spread: spreadOf(pool, typical), sparse }
}

function unitOf(interval: IntervalType): string {
    return interval === 'minute' || interval === 'second' ? 'minute' : interval
}

function on(day: string, interval: IntervalType): string {
    return `${interval === 'day' ? 'on' : 'in'} ${dateLabel(day, interval)}`
}

interface ScoredMoment {
    moment: ChartMoment
    score: number
}

// A peak is judged against the level around it. After a lasting change of level, that is the level of its own side.
function peakMoments(
    values: number[],
    [first, last]: [number, number],
    series: MomentSeries,
    options: MomentOptions
): ScoredMoment[] {
    const base = baselineOf(values.slice(first, last + 1))
    const threshold = Math.max(base.typical * 1.8, base.typical + 2.5 * base.spread)
    const maxWidth = Math.max(3, Math.floor((last - first + 1) * 0.2))
    const candidates: number[] = []
    for (let index = first; index <= last; index++) {
        if (values[index] > threshold) {
            candidates.push(index)
        }
    }
    candidates.sort((a, b) => values[b] - values[a])

    const peaks: { start: number; end: number; anchor: number }[] = []
    for (const anchor of candidates) {
        if (peaks.some((peak) => anchor >= peak.start - 1 && anchor <= peak.end + 1)) {
            continue
        }
        const floor = base.typical + (values[anchor] - base.typical) / 2
        let start = anchor
        let end = anchor
        while (start > first && values[start - 1] >= floor) {
            start--
        }
        while (end < last && values[end + 1] >= floor) {
            end++
        }
        // A wide stretch above the threshold is a new level, which the shift moment covers.
        if (end - start + 1 > maxWidth) {
            continue
        }
        peaks.push({ start, end, anchor })
    }

    return peaks.map(({ start, end, anchor }) => ({
        score: base.typical > 0 ? values[anchor] / base.typical : values[anchor],
        moment: {
            id: `peak-${anchor}`,
            kind: 'peak',
            range: [start, end],
            direction: 'up',
            title: `A peak ${on(series.days[anchor], options.interval)}`,
        },
    }))
}

function dipMoment(values: number[], base: Baseline, series: MomentSeries, options: MomentOptions): ChartMoment | null {
    if (base.typical <= 0) {
        return null
    }
    const limit = base.typical * 0.1
    let best: [number, number] | null = null
    let runStart: number | null = null
    for (let index = 0; index <= values.length; index++) {
        const low = index < values.length && values[index] <= limit
        if (low && runStart === null) {
            runStart = index
        } else if (!low && runStart !== null) {
            if (!best || index - runStart > best[1] - best[0] + 1) {
                best = [runStart, index - 1]
            }
            runStart = null
        }
    }

    if (best && best[1] - best[0] >= 1) {
        const [start, end] = best
        const empty = values.slice(start, end + 1).every((value) => value === 0)
        return {
            id: `dip-${start}`,
            kind: 'dip',
            range: best,
            direction: 'down',
            title: `${empty ? 'Nothing' : 'Almost nothing'} for ${end - start + 1} ${unitOf(options.interval)}s`,
        }
    }

    const lowest = values.indexOf(Math.min(...values))
    if (base.sparse || values[lowest] > base.typical * 0.4 || base.typical - values[lowest] < 2.5 * base.spread) {
        return null
    }
    return {
        id: `dip-${lowest}`,
        kind: 'dip',
        range: [lowest, lowest],
        direction: 'down',
        title: `A dip ${on(series.days[lowest], options.interval)}`,
    }
}

function shiftMoment(
    values: number[],
    base: Baseline,
    series: MomentSeries,
    options: MomentOptions
): ChartMoment | null {
    const edge = Math.max(3, Math.floor(values.length * 0.2))
    if (base.sparse || values.length < edge * 2 || values.length > MAX_SHIFT_POINTS) {
        return null
    }
    // The split is where each side sits closest to its own median. A score of the gap alone ties along the step.
    let best: { index: number; before: number; after: number; score: number; cost: number } | null = null
    for (let index = edge; index <= values.length - edge; index++) {
        const head = values.slice(0, index)
        const tail = values.slice(index)
        const before = median(head)
        const after = median(tail)
        const cost =
            head.reduce((sum, value) => sum + Math.abs(value - before), 0) +
            tail.reduce((sum, value) => sum + Math.abs(value - after), 0)
        if (!best || cost < best.cost) {
            const within = Math.max(spreadOf(head, before), spreadOf(tail, after), Number.EPSILON)
            best = { index, before, after, score: Math.abs(after - before) / within, cost }
        }
    }
    if (!best || best.score < 2.5 || best.before <= 0) {
        return null
    }
    const ratio = best.after / best.before
    if (ratio < 1.4 && ratio > 0.7) {
        return null
    }
    return {
        id: `shift-${best.index}`,
        kind: 'shift',
        range: [best.index, values.length - 1],
        direction: ratio > 1 ? 'up' : 'down',
        title: `${ratio > 1 ? 'Higher' : 'Lower'} since ${dateLabel(series.days[best.index], options.interval)}`,
    }
}

/** Finds what stands out on a chart: up to two peaks, an empty stretch or a dip, and a lasting change of level. */
export function findChartMoments(series: MomentSeries, options: MomentOptions): ChartMoment[] {
    const values = series.data.slice(0, series.data.length - options.incompletePoints)
    if (values.length < MIN_POINTS || values.every((value) => value === 0)) {
        return []
    }
    const base = baselineOf(values)

    const shift = shiftMoment(values, base, series, options)
    const boundary = shift?.range[0]
    const sides: [number, number][] = boundary
        ? [
              [0, boundary - 1],
              [boundary, values.length - 1],
          ]
        : [[0, values.length - 1]]
    const peaks = sides
        .flatMap((side) => peakMoments(values, side, series, options))
        .sort((a, b) => b.score - a.score)
        .slice(0, MAX_PEAKS)
        .map((peak) => peak.moment)

    return [...peaks, dipMoment(values, base, series, options), shift].filter(
        (moment): moment is ChartMoment => !!moment
    )
}
