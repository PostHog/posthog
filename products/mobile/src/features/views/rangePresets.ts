import type { RangeChoice, RangePresetKey, RangeStepUnit, SavedRange } from '@/model/views'

// Labels and values from the web's `dateMapping` in `frontend/src/lib/utils/dateFilters.ts`. The same strings make
// the same server cache entry, so a phone read of "Last 7 days" can reuse what the web computed.

export interface RangePreset {
    key: RangePresetKey
    /** The web's label. */
    label: string
    /** The shorter text on a chip. */
    chipLabel: string
    dateFrom: string
    /** Always sent, also when null, so a saved `date_to` never survives the override. */
    dateTo: string | null
    /** How the ‹ › buttons step from this preset. Null: no stepping (All time). */
    unit: RangeStepUnit | null
}

function preset(
    key: RangePresetKey,
    label: string,
    dateFrom: string,
    dateTo: string | null,
    unit: RangeStepUnit | null,
    chipLabel: string = label
): RangePreset {
    return { key, label, chipLabel, dateFrom, dateTo, unit }
}

export const RANGE_PRESETS: Record<RangePresetKey, RangePreset> = {
    today: preset('today', 'Today', 'dStart', null, 'day'),
    yesterday: preset('yesterday', 'Yesterday', '-1dStart', '-1dEnd', 'day'),
    '24h': preset('24h', 'Last 24 hours', '-24h', null, 'hours', '24 hours'),
    '7d': preset('7d', 'Last 7 days', '-7d', null, 'days', '7 days'),
    '30d': preset('30d', 'Last 30 days', '-30d', null, 'days', '30 days'),
    '90d': preset('90d', 'Last 90 days', '-90d', null, 'days', '90 days'),
    this_week: preset('this_week', 'This week', 'wStart', null, 'week'),
    this_month: preset('this_month', 'This month', 'mStart', null, 'month'),
    last_month: preset('last_month', 'Last month', '-1mStart', '-1mEnd', 'month'),
    this_year: preset('this_year', 'This year', 'yStart', null, 'year'),
    all: preset('all', 'All time', 'all', null, null),
    '1h': preset('1h', 'Last hour', '-1h', null, 'hours'),
    '48h': preset('48h', 'Last 48 hours', '-48h', null, 'hours'),
    '14d': preset('14d', 'Last 14 days', '-14d', null, 'days'),
    '180d': preset('180d', 'Last 180 days', '-180d', null, 'days'),
    last_week: preset('last_week', 'Last week', '-1wStart', '-1wEnd', 'week'),
}

/** Chip order follows phone use: Today, Yesterday and 24 hours lead. */
export const CHIP_PRESETS: readonly RangePresetKey[] = ['today', 'yesterday', '24h', '7d', '30d', '90d']

/** The rows under "More". There is no "Last year": the server resolves `-1yEnd` to the end of this month last year. */
export const MORE_PRESETS: readonly RangePresetKey[] = [
    'this_week',
    'this_month',
    'last_month',
    'this_year',
    'all',
    '1h',
    '48h',
    '14d',
    '180d',
    'last_week',
]

export function presetForValues(dateFrom: string | null, dateTo: string | null): RangePreset | undefined {
    return Object.values(RANGE_PRESETS).find(
        (candidate) => candidate.dateFrom === dateFrom && (candidate.dateTo ?? null) === (dateTo ?? null)
    )
}

/** The values a choice sends. `explicitDate` is present only for a fixed range. */
export interface RangeValues {
    date_from: string
    date_to: string | null
    explicitDate?: boolean
}

export function rangeValues(choice: RangeChoice): RangeValues {
    if (choice.kind === 'preset') {
        const { dateFrom, dateTo } = RANGE_PRESETS[choice.key]
        return { date_from: dateFrom, date_to: dateTo }
    }
    return { date_from: choice.dateFrom, date_to: choice.dateTo, explicitDate: choice.explicitDate }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const
const DAY_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/

interface WallTime {
    year: number
    month: number
    day: number
    time: string | null
}

// The date and time as written, which for the server's resolved ranges is the project timezone.
function wallTime(value: string): WallTime | null {
    const day = DAY_ONLY.exec(value)
    if (day) {
        return { year: Number(day[1]), month: Number(day[2]), day: Number(day[3]), time: null }
    }
    const dateTime = DATE_TIME.exec(value)
    if (dateTime) {
        return {
            year: Number(dateTime[1]),
            month: Number(dateTime[2]),
            day: Number(dateTime[3]),
            time: `${dateTime[4]}:${dateTime[5]}`,
        }
    }
    return null
}

function monthDay(time: WallTime): string {
    return `${MONTHS[time.month - 1] ?? ''} ${time.day}`
}

/**
 * The web's range format: "Oct 13", "Oct 6 – 12", "Sep 29 – Oct 6", "Dec 29, 2025 – Jan 4, 2026", and times for
 * windows of hours. Screen readers get `formatRangeSpanForSpeech`.
 */
export function formatRangeSpan(from: string, to: string, separator = ' – '): string {
    const a = wallTime(from)
    const b = wallTime(to)
    if (!a || !b) {
        return `${from}${separator}${to}`
    }
    if (a.time !== null || b.time !== null) {
        return `${monthDay(a)} ${a.time ?? '00:00'}${separator}${monthDay(b)} ${b.time ?? '00:00'}`
    }
    if (a.year !== b.year) {
        return `${monthDay(a)}, ${a.year}${separator}${monthDay(b)}, ${b.year}`
    }
    if (a.month === b.month && a.day === b.day) {
        return monthDay(a)
    }
    if (a.month === b.month) {
        return `${monthDay(a)}${separator}${b.day}`
    }
    return `${monthDay(a)}${separator}${monthDay(b)}`
}

export function formatRangeSpanForSpeech(from: string, to: string): string {
    return formatRangeSpan(from, to, ' to ')
}

const RELATIVE = /^-(\d+)([hdwmy])$/
const RELATIVE_NOUNS: Record<string, string> = { h: 'hour', d: 'day', w: 'week', m: 'month', y: 'year' }

/**
 * The header label of a choice, or of the saved range when there is no choice. Null when the saved range has no dates,
 * which on a dashboard means each tile keeps its own range.
 */
export function rangeLabel(choice: RangeChoice | null, saved: SavedRange): string | null {
    if (choice?.kind === 'preset') {
        return RANGE_PRESETS[choice.key].label
    }
    if (choice?.kind === 'fixed') {
        return formatRangeSpan(choice.dateFrom, choice.dateTo)
    }
    if (!saved.dateFrom) {
        return null
    }
    const known = presetForValues(saved.dateFrom, saved.dateTo)
    if (known) {
        return known.label
    }
    const relative = RELATIVE.exec(saved.dateFrom)
    const noun = relative?.[2] ? RELATIVE_NOUNS[relative[2]] : undefined
    if (relative && noun && !saved.dateTo) {
        const amount = Number(relative[1])
        return amount === 1 ? `Last ${noun}` : `Last ${amount} ${noun}s`
    }
    if (wallTime(saved.dateFrom)) {
        return formatRangeSpan(saved.dateFrom, saved.dateTo ?? saved.dateFrom)
    }
    return saved.dateFrom
}

/** True when the choice sends the same dates as the saved range, so "Reset to saved range" stays hidden. */
export function isSavedRange(choice: RangeChoice | null, saved: SavedRange): boolean {
    if (!choice) {
        return true
    }
    const values = rangeValues(choice)
    return values.date_from === saved.dateFrom && (values.date_to ?? null) === (saved.dateTo ?? null)
}

/**
 * The choice for two calendar taps, in either order: date-only strings in the project timezone. The server takes a
 * day-only `date_to` as the end of that day.
 */
export function customRange(first: string, second: string): RangeChoice {
    const [dateFrom, dateTo] = first <= second ? [first, second] : [second, first]
    return {
        kind: 'fixed',
        dateFrom,
        dateTo,
        explicitDate: false,
        unit: dateFrom === dateTo ? 'day' : 'days',
        origin: null,
    }
}
