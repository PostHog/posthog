import { dayjs } from 'lib/dayjs'

import type { IntervalType } from '~/types'

import { mark } from './storyMarks'

export type ChartMomentKind = 'overview' | 'peak' | 'dip' | 'shift' | 'rhythm' | 'latest'

export interface ChartMoment {
    id: string
    kind: ChartMomentKind
    /** The points the moment covers, as inclusive index ranges. Empty when it covers the whole chart. */
    ranges: [number, number][]
    /** The point that the marker sits on. Null when the moment is not about one point. */
    anchorIndex: number | null
    /** Whether the moment is a rise or a fall, for the search for its cause. Null when it is neither. */
    direction: 'up' | 'down' | null
    title: string
    summary: string
}

export interface MomentSeries {
    data: number[]
    days: string[]
}

export interface MomentOptions {
    interval: IntervalType
    incompletePoints: number
    formatValue: (value: number) => string
}

const MAX_PEAKS = 2
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

function isWeekend(day: string): boolean {
    return [0, 6].includes(dayjs(day).day())
}

function unitOf(interval: IntervalType): string {
    return interval === 'minute' || interval === 'second' ? 'minute' : interval
}

function dateLabel(day: string, interval: IntervalType): string {
    const date = dayjs(day)
    switch (interval) {
        case 'second':
        case 'minute':
        case 'hour':
            return date.format('MMM D, HH:mm')
        case 'week':
            return `the week of ${date.format('MMMM D')}`
        case 'month':
            return date.format('MMMM YYYY')
        default:
            return date.format('MMMM D')
    }
}

function times(ratio: number): string {
    return `${ratio >= 10 ? Math.round(ratio) : Math.round(ratio * 10) / 10} times`
}

// A typical level is a median or an average, and its decimals say nothing a person can use.
function level(value: number): number {
    return value >= 10 ? Math.round(value) : Math.round(value * 10) / 10
}

function percent(share: number): string {
    return `${Math.round(Math.abs(share) * 100)}%`
}

function comparedWithTypical(value: number, base: Baseline, unit: string, format: (value: number) => string): string {
    const typicalUnit = `a typical ${base.sparse ? 'active ' : ''}${unit} (${format(level(base.typical))})`
    if (base.typical <= 0) {
        return ''
    }
    const ratio = value / base.typical
    if (ratio >= 2) {
        return `${mark('value', times(ratio))} ${typicalUnit}`
    }
    if (Math.abs(ratio - 1) <= 0.2) {
        return `in line with ${typicalUnit}`
    }
    return `${mark('value', `${percent(ratio - 1)} ${ratio > 1 ? 'above' : 'below'}`)} ${typicalUnit}`
}

function overviewMoment(values: number[], base: Baseline, unit: string, options: MomentOptions): ChartMoment {
    const { formatValue } = options
    const sentences: string[] = []
    if (base.sparse) {
        const active = values.filter((value) => value > 0).length
        sentences.push(
            `Only ${mark('value', `${active} of ${values.length} ${unit}s`)} have any activity. A typical active ${unit} is ${mark('value', formatValue(level(base.typical)))}.`
        )
    } else {
        sentences.push(`A typical ${unit} is ${mark('value', formatValue(level(base.typical)))}.`)
    }
    sentences.push(`The range runs from ${formatValue(Math.min(...values))} to ${formatValue(Math.max(...values))}.`)
    const third = Math.floor(values.length / 3)
    if (third >= 2 && !base.sparse) {
        const start = mean(values.slice(0, third))
        const end = mean(values.slice(-third))
        if (start > 0) {
            const change = end / start - 1
            sentences.push(
                Math.abs(change) < 0.1
                    ? 'It ends at about the level it starts at.'
                    : `It ends ${mark('value', `${percent(change)} ${change > 0 ? 'higher' : 'lower'}`)} than it starts.`
            )
        }
    }
    return {
        id: 'overview',
        kind: 'overview',
        ranges: [],
        anchorIndex: null,
        direction: null,
        title: 'The big picture',
        summary: sentences.join(' '),
    }
}

interface ScoredMoment {
    moment: ChartMoment
    score: number
}

// A peak is judged against the level around it. After a lasting change of level, that is the level of its own side.
function peakMoments(
    values: number[],
    [first, last]: [number, number],
    unit: string,
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

    return peaks.map(({ start, end, anchor }) => {
        const on = dateLabel(series.days[anchor], options.interval)
        const when = `${options.interval === 'day' ? 'on' : 'in'} ${on}`
        const compared = comparedWithTypical(values[anchor], base, unit, options.formatValue)
        return {
            score: base.typical > 0 ? values[anchor] / base.typical : values[anchor],
            moment: {
                id: `peak-${anchor}`,
                kind: 'peak' as const,
                ranges: [[start, end]],
                anchorIndex: anchor,
                direction: 'up' as const,
                title: `A peak ${when}`,
                summary: `${mark('value', options.formatValue(values[anchor]))}${compared ? `, ${compared}` : ''}.`,
            },
        }
    })
}

function dipMoment(
    values: number[],
    base: Baseline,
    unit: string,
    series: MomentSeries,
    options: MomentOptions
): ChartMoment | null {
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
        const length = end - start + 1
        const empty = values.slice(start, end + 1).every((value) => value === 0)
        const from = mark('date', dateLabel(series.days[start], options.interval))
        const to = mark('date', dateLabel(series.days[end], options.interval))
        return {
            id: `dip-${start}`,
            kind: 'dip',
            ranges: [best],
            anchorIndex: Math.floor((start + end) / 2),
            direction: 'down',
            title: `${empty ? 'Nothing' : 'Almost nothing'} for ${length} ${unit}s`,
            summary: empty
                ? `From ${from} to ${to} there is no activity at all.`
                : `From ${from} to ${to} the level stays under ${options.formatValue(level(limit))}.`,
        }
    }

    const lowest = values.indexOf(Math.min(...values))
    if (base.sparse || values[lowest] > base.typical * 0.4 || base.typical - values[lowest] < 2.5 * base.spread) {
        return null
    }
    const on = dateLabel(series.days[lowest], options.interval)
    return {
        id: `dip-${lowest}`,
        kind: 'dip',
        ranges: [[lowest, lowest]],
        anchorIndex: lowest,
        direction: 'down',
        title: `A dip on ${on}`,
        summary: `${mark('value', options.formatValue(values[lowest]))}, ${comparedWithTypical(values[lowest], base, unit, options.formatValue)}.`,
    }
}

function shiftMoment(
    values: number[],
    base: Baseline,
    unit: string,
    series: MomentSeries,
    options: MomentOptions
): ChartMoment | null {
    const edge = Math.max(3, Math.floor(values.length * 0.2))
    if (base.sparse || values.length < edge * 2) {
        return null
    }
    let best: { index: number; before: number; after: number; score: number } | null = null
    for (let index = edge; index <= values.length - edge; index++) {
        const before = median(values.slice(0, index))
        const after = median(values.slice(index))
        const within = Math.max(
            spreadOf(values.slice(0, index), before),
            spreadOf(values.slice(index), after),
            Number.EPSILON
        )
        const score = Math.abs(after - before) / within
        if (!best || score > best.score) {
            best = { index, before, after, score }
        }
    }
    if (!best || best.score < 2.5 || best.before <= 0) {
        return null
    }
    const ratio = best.after / best.before
    if (ratio < 1.4 && ratio > 0.7) {
        return null
    }
    const since = dateLabel(series.days[best.index], options.interval)
    const change = mark('value', ratio >= 2 ? times(ratio) : `${percent(ratio - 1)} ${ratio > 1 ? 'higher' : 'lower'}`)
    return {
        id: `shift-${best.index}`,
        kind: 'shift',
        ranges: [[best.index, values.length - 1]],
        anchorIndex: best.index,
        direction: ratio > 1 ? 'up' : 'down',
        title: `${ratio > 1 ? 'Higher' : 'Lower'} since ${since}`,
        summary: `Before ${mark('date', since)} a typical ${unit} was ${options.formatValue(level(best.before))}. Since then it is ${mark('value', options.formatValue(level(best.after)))}, ${ratio >= 2 ? `${change} as much` : change}.`,
    }
}

function rhythmMoment(
    values: number[],
    base: Baseline,
    series: MomentSeries,
    options: MomentOptions
): ChartMoment | null {
    if (options.interval !== 'day' || values.length < 14 || base.sparse) {
        return null
    }
    const weekendDays = values.map((_, index) => isWeekend(series.days[index]))
    // Medians, so one peak on a Tuesday does not make every weekday look busy.
    const weekend = median(values.filter((_, index) => weekendDays[index]))
    const weekday = median(values.filter((_, index) => !weekendDays[index]))
    if (weekday <= 0 || weekend <= 0) {
        return null
    }
    const ratio = weekend / weekday
    if (ratio > 0.6 && ratio < 1.5) {
        return null
    }
    const ranges: [number, number][] = []
    weekendDays.forEach((weekendDay, index) => {
        if (!weekendDay) {
            return
        }
        const last = ranges[ranges.length - 1]
        if (last && last[1] === index - 1) {
            last[1] = index
        } else {
            ranges.push([index, index])
        }
    })
    return {
        id: 'rhythm',
        kind: 'rhythm',
        ranges,
        anchorIndex: null,
        direction: null,
        title: ratio < 1 ? 'Quieter at weekends' : 'Busier at weekends',
        summary: `A typical Saturday or Sunday is ${mark('value', options.formatValue(level(weekend)))}, ${mark('value', `${percent(ratio - 1)} ${ratio < 1 ? 'below' : 'above'}`)} a typical weekday (${options.formatValue(level(weekday))}).`,
    }
}

function latestMoment(
    values: number[],
    base: Baseline,
    unit: string,
    typicalUnit: string,
    series: MomentSeries,
    options: MomentOptions,
    taken: ChartMoment[]
): ChartMoment | null {
    const last = values.length - 1
    const inProgress = options.incompletePoints > 0 ? series.data[series.data.length - 1] : null
    if (inProgress === null && taken.some((moment) => moment.anchorIndex === last)) {
        return null
    }
    const sentences = [
        `${mark('date', dateLabel(series.days[last], options.interval))}: ${mark('value', options.formatValue(values[last]))}`,
    ]
    const compared = comparedWithTypical(values[last], base, typicalUnit, options.formatValue)
    sentences[0] += compared ? `, ${compared}.` : '.'
    if (inProgress !== null) {
        const current = unit === 'day' ? 'Today' : `This ${unit}`
        sentences.push(
            `${current} is not over. It has ${mark('value', options.formatValue(inProgress))} so far, so the end of the line will still move.`
        )
    }
    return {
        id: 'latest',
        kind: 'latest',
        ranges: [[last, series.data.length - 1]],
        anchorIndex: last,
        direction: values[last] >= base.typical ? 'up' : 'down',
        title: `The latest full ${unit}`,
        summary: sentences.join(' '),
    }
}

export function findChartMoments(series: MomentSeries, options: MomentOptions): ChartMoment[] {
    const values = series.data.slice(0, series.data.length - options.incompletePoints)
    if (values.length < MIN_POINTS || values.every((value) => value === 0)) {
        return []
    }
    const base = baselineOf(values)
    const unit = unitOf(options.interval)

    const shift = shiftMoment(values, base, unit, series, options)
    const boundary = shift?.ranges[0][0]
    const sides: [number, number][] = boundary
        ? [
              [0, boundary - 1],
              [boundary, values.length - 1],
          ]
        : [[0, values.length - 1]]
    const peaks = sides
        .flatMap((side) => peakMoments(values, side, unit, series, options))
        .sort((a, b) => b.score - a.score)
        .slice(0, MAX_PEAKS)
        .map((peak) => peak.moment)

    const dated = [...peaks, dipMoment(values, base, unit, series, options), shift]
        .filter((moment): moment is ChartMoment => !!moment)
        .sort((a, b) => (a.ranges[0]?.[0] ?? 0) - (b.ranges[0]?.[0] ?? 0))
    const rhythm = rhythmMoment(values, base, series, options)

    // The latest point is compared with the level the chart is at now. With a weekend pattern, that is the level of
    // the same kind of day, or every Saturday would read as a fall.
    const from = boundary ?? 0
    const lastIsWeekend = isWeekend(series.days[values.length - 1])
    const sameKind = values.slice(from).filter((_, index) => isWeekend(series.days[from + index]) === lastIsWeekend)
    const compareByKind = !!rhythm && sameKind.length >= 2
    const current = compareByKind ? baselineOf(sameKind) : boundary ? baselineOf(values.slice(boundary)) : base
    const currentUnit = compareByKind ? (lastIsWeekend ? 'weekend day' : 'weekday') : unit

    return [
        overviewMoment(values, base, unit, options),
        ...dated,
        rhythm,
        latestMoment(values, current, unit, currentUnit, series, options, dated),
    ].filter((moment): moment is ChartMoment => !!moment)
}
