import { mark } from './storyMarks'

export interface StoryFactsOptions {
    interval: string
    lastPointInProgress: boolean
    formatValue: (value: number) => string
}

interface Baseline {
    typical: number
    sparse: boolean
}

const MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]
/** A series with this share of zero points is compared by its non-zero points only. */
const SPARSE_SHARE = 0.3
const MIN_POINTS = 3

function mean(values: number[]): number {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

function median(values: number[]): number {
    if (!values.length) {
        return 0
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
}

function baselineOf(values: number[]): Baseline {
    const active = values.filter((value) => value !== 0)
    const sparse = active.length > 0 && values.length - active.length >= values.length * SPARSE_SHARE
    return { typical: median(sparse ? active : values), sparse }
}

function unitOf(interval: string): string {
    return interval
}

// Parsed by hand: `new Date('2026-10-02')` is midnight UTC, which reads as October 1 west of Greenwich.
export function dateLabel(day: string, interval: string): string {
    const [, year, month, date, hour, minute, second] =
        /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(day) ?? []
    if (!year || !month || !date) {
        return day
    }
    const monthName = MONTHS[Number(month) - 1] ?? month
    switch (interval) {
        case 'second':
            return `${monthName.slice(0, 3)} ${Number(date)}, ${hour ?? '00'}:${minute ?? '00'}:${second ?? '00'}`
        case 'minute':
        case 'hour':
            return `${monthName.slice(0, 3)} ${Number(date)}, ${hour ?? '00'}:${minute ?? '00'}`
        case 'week':
            return `the week of ${monthName} ${Number(date)}`
        case 'month':
            return `${monthName} ${year}`
        case 'quarter':
            return `Q${Math.floor((Number(month) - 1) / 3) + 1} ${year}`
        case 'year':
            return year
        default:
            return `${monthName} ${Number(date)}`
    }
}

function times(ratio: number): string {
    return `${ratio >= 10 ? Math.round(ratio) : Math.round(ratio * 10) / 10} times`
}

// A typical level is a median, and its decimals say nothing a person can use. A value below 1
// keeps two significant digits, so a rate like 0.02 survives until the unit formatter runs.
function level(value: number): number {
    const size = Math.abs(value)
    if (size >= 10) {
        return Math.round(value)
    }
    if (size >= 1 || size === 0) {
        return Math.round(value * 10) / 10
    }
    const factor = 10 ** (Math.ceil(-Math.log10(size)) + 1)
    return Math.round(value * factor) / factor
}

function percent(share: number): string {
    return `${Math.round(Math.abs(share) * 100)}%`
}

function comparison(value: number, typical: number, against: string): string {
    const ratio = value / typical
    if (ratio >= 2) {
        return `${mark('value', times(ratio))} ${against}`
    }
    if (Math.abs(ratio - 1) <= 0.2) {
        return `in line with ${against}`
    }
    return `${mark('value', `${percent(ratio - 1)} ${ratio > 1 ? 'above' : 'below'}`)} ${against}`
}

function completeValues(data: number[], options: StoryFactsOptions): number[] {
    return options.lastPointInProgress ? data.slice(0, -1) : data
}

function baselineAround(data: number[], [start, end]: [number, number], options: StoryFactsOptions): Baseline | null {
    const outside = completeValues(data, options).filter((_, index) => index < start || index > end)
    return outside.length >= MIN_POINTS ? baselineOf(outside) : null
}

/** The point a chapter's marker sits on: the one furthest from the rest of the chart. */
export function anchorOf(data: number[], range: [number, number], options: StoryFactsOptions): number {
    const [start, end] = range
    // An unfinished last point reads low, so it takes the marker only when it is the whole chapter.
    const last = options.lastPointInProgress && end === data.length - 1 && end > start ? end - 1 : end
    const typical = baselineAround(data, range, options)?.typical ?? median(completeValues(data, options))
    let anchor = start
    for (let index = start; index <= last; index++) {
        if (Math.abs(data[index]! - typical) > Math.abs(data[anchor]! - typical)) {
            anchor = index
        }
    }
    return anchor
}

export function overviewFacts(data: number[], options: StoryFactsOptions): string {
    const values = completeValues(data, options)
    if (values.length < MIN_POINTS) {
        return ''
    }
    const { formatValue } = options
    const unit = unitOf(options.interval)
    const base = baselineOf(values)
    const sentences: string[] = []
    if (base.sparse) {
        const active = values.filter((value) => value !== 0).length
        sentences.push(
            `Only ${mark('value', `${active} of ${values.length} ${unit}s`)} are not zero. A typical non-zero ${unit} is ${mark('value', formatValue(level(base.typical)))}.`
        )
    } else {
        sentences.push(`A typical ${unit} is ${mark('value', formatValue(level(base.typical)))}.`)
    }
    let lowest = values[0]!
    let highest = values[0]!
    for (const value of values) {
        lowest = Math.min(lowest, value)
        highest = Math.max(highest, value)
    }
    sentences.push(`The range runs from ${formatValue(lowest)} to ${formatValue(highest)}.`)
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
    return sentences.join(' ')
}

function pointFacts(data: number[], days: string[], index: number, options: StoryFactsOptions): string {
    const unit = unitOf(options.interval)
    const label = dateLabel(days[index] ?? '', options.interval)
    const when = `${options.interval === 'day' ? 'on' : unit === 'minute' || unit === 'hour' ? 'at' : 'in'} ${mark('date', label)}`
    const value = mark('value', options.formatValue(data[index]!))
    if (options.lastPointInProgress && index === data.length - 1) {
        return `${value} so far ${when}. This ${unit} is not over yet, so the number can still change.`
    }
    const base = baselineAround(data, [index, index], options)
    const typicalUnit = `a typical ${base?.sparse ? 'non-zero ' : ''}${unit}`
    const compared =
        base && base.typical > 0
            ? comparison(data[index]!, base.typical, `${typicalUnit} (${options.formatValue(level(base.typical))})`)
            : ''
    return `${value} ${when}${compared ? `, ${compared}` : ''}.`
}

function stretchFacts(data: number[], days: string[], range: [number, number], options: StoryFactsOptions): string {
    const [start, end] = range
    const unit = unitOf(options.interval)
    const from = mark('date', dateLabel(days[start] ?? '', options.interval))
    const to = mark('date', dateLabel(days[end] ?? '', options.interval))
    const includesInProgress = options.lastPointInProgress && end === data.length - 1
    const values = data.slice(start, includesInProgress ? end : end + 1)
    const ongoing = includesInProgress ? ` This ${unit} is not over yet.` : ''
    if (!values.length) {
        return pointFacts(data, days, end, options)
    }
    if (data.slice(start, end + 1).every((value) => value === 0)) {
        return `From ${from} to ${to} every value is zero.${ongoing}`
    }
    const base = baselineAround(data, range, options)
    // A sparse chart is judged by its non-zero points, so the stretch leaves out its zeros as well.
    const nonZero = values.filter((value) => value !== 0)
    const typical = median(base?.sparse && nonZero.length ? nonZero : values)
    const typicalUnit = `a typical ${base?.sparse ? 'non-zero ' : ''}${unit}`
    const compared =
        base && base.typical > 0
            ? comparison(
                  typical,
                  base.typical,
                  `the rest of the chart (${options.formatValue(level(base.typical))} on ${typicalUnit})`
              )
            : ''
    return `From ${from} to ${to}, ${typicalUnit} is ${mark('value', options.formatValue(level(typical)))}${compared ? `, ${compared}` : ''}.${ongoing}`
}

export function chapterFacts(
    data: number[],
    days: string[],
    range: [number, number],
    options: StoryFactsOptions
): string {
    return range[0] === range[1] ? pointFacts(data, days, range[0], options) : stretchFacts(data, days, range, options)
}
