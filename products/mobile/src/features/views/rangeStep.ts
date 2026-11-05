import type { RangeChoice, RangePresetKey, RangeStepUnit, ResolvedRange, SavedRange } from '@/model/views'

import { presetForValues, RANGE_PRESETS } from './rangePresets'

// Steps work on the window the server resolved (`resolved_date_range`, in the project timezone), not on the phone
// clock, so a step lands on the same days the server would compute for the web.

export interface StepContext {
    /** The window the server resolved for the current choice. Stepping needs it. */
    resolved: ResolvedRange | null
    /** Today in the project timezone, `YYYY-MM-DD`. See `projectToday`. */
    today: string
    /** Server epoch ms, for windows of hours. */
    now: number
}

export type StepDirection = -1 | 1

const DAY_MS = 86_400_000
const HOUR_TOLERANCE_MS = 60_000

function toUtc(day: string): number {
    const [year, month, date] = day.split('-').map(Number)
    return Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1)
}

function fromUtc(ms: number): string {
    return new Date(ms).toISOString().slice(0, 10)
}

function addDays(day: string, days: number): string {
    return fromUtc(toUtc(day) + days * DAY_MS)
}

function daysBetween(from: string, to: string): number {
    return Math.round((toUtc(to) - toUtc(from)) / DAY_MS)
}

function startOfMonth(day: string, monthsAhead = 0): string {
    const date = new Date(toUtc(day))
    return fromUtc(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + monthsAhead, 1))
}

function endOfMonth(day: string): string {
    return addDays(startOfMonth(day, 1), -1)
}

function startOfYear(day: string, yearsAhead = 0): string {
    return `${Number(day.slice(0, 4)) + yearsAhead}-01-01`
}

/**
 * Today in the project timezone. The resolved range carries the project's UTC offset (`2026-10-14T23:59:59-07:00`),
 * so applying that offset to server now gives the project's date without a timezone database. Without one, the
 * phone's own offset is the closer guess. UTC would enable tomorrow in the calendar on every evening in the Americas.
 */
export function projectToday(resolvedTo: string | null, now: number): string {
    const offset = resolvedTo ? /([+-])(\d{2}):(\d{2})$/.exec(resolvedTo) : null
    const offsetMs = offset
        ? (offset[1] === '-' ? -1 : 1) * (Number(offset[2]) * 60 + Number(offset[3])) * 60_000
        : -new Date(now).getTimezoneOffset() * 60_000
    return fromUtc(now + offsetMs)
}

interface Current {
    unit: RangeStepUnit | null
    origin: RangePresetKey | null
}

function currentOf(choice: RangeChoice | null, saved: SavedRange): Current {
    if (choice?.kind === 'fixed') {
        return { unit: choice.unit, origin: choice.origin }
    }
    const preset = choice?.kind === 'preset' ? RANGE_PRESETS[choice.key] : presetForValues(saved.dateFrom, saved.dateTo)
    if (preset) {
        return { unit: preset.unit, origin: preset.key }
    }
    if (choice === null && saved.dateFrom && /^-\d+d$/.test(saved.dateFrom) && !saved.dateTo) {
        return { unit: 'days', origin: null }
    }
    return { unit: null, origin: null }
}

function fixedDays(dateFrom: string, dateTo: string, unit: RangeStepUnit, origin: RangePresetKey | null): RangeChoice {
    return { kind: 'fixed', dateFrom, dateTo, explicitDate: false, unit, origin }
}

const presetChoice = (key: RangePresetKey): RangeChoice => ({ kind: 'preset', key })

function stepDay(
    day: string,
    direction: StepDirection,
    today: string,
    origin: RangePresetKey | null
): RangeChoice | null {
    const next = addDays(day, direction)
    if (next > today) {
        return null
    }
    if (next === today) {
        return presetChoice('today')
    }
    if (next === addDays(today, -1)) {
        return presetChoice('yesterday')
    }
    return fixedDays(next, next, 'day', origin)
}

function stepWeek(
    from: string,
    to: string,
    direction: StepDirection,
    today: string,
    origin: RangePresetKey | null
): RangeChoice | null {
    if (direction === -1) {
        return fixedDays(addDays(from, -7), addDays(from, -1), 'week', origin)
    }
    if (to >= today) {
        return null
    }
    const nextFrom = addDays(from, 7)
    const nextTo = addDays(nextFrom, 6)
    return nextTo >= today ? presetChoice('this_week') : fixedDays(nextFrom, nextTo, 'week', origin)
}

function stepMonth(
    from: string,
    to: string,
    direction: StepDirection,
    today: string,
    origin: RangePresetKey | null
): RangeChoice | null {
    if (direction === -1) {
        const start = startOfMonth(from, -1)
        return start === startOfMonth(today, -1)
            ? presetChoice('last_month')
            : fixedDays(start, addDays(from, -1), 'month', origin)
    }
    if (to >= today) {
        return null
    }
    const start = startOfMonth(from, 1)
    if (start === startOfMonth(today)) {
        return presetChoice('this_month')
    }
    return start === startOfMonth(today, -1)
        ? presetChoice('last_month')
        : fixedDays(start, endOfMonth(start), 'month', origin)
}

function stepYear(
    from: string,
    to: string,
    direction: StepDirection,
    today: string,
    origin: RangePresetKey | null
): RangeChoice | null {
    if (direction === -1) {
        return fixedDays(startOfYear(from, -1), addDays(from, -1), 'year', origin)
    }
    if (to >= today) {
        return null
    }
    const start = startOfYear(from, 1)
    return start === startOfYear(today)
        ? presetChoice('this_year')
        : fixedDays(start, addDays(startOfYear(from, 2), -1), 'year', origin)
}

function stepDays(
    from: string,
    to: string,
    direction: StepDirection,
    today: string,
    origin: RangePresetKey | null
): RangeChoice | null {
    const span = daysBetween(from, to) + 1
    if (direction === 1 && to >= today) {
        return null
    }
    const nextFrom = addDays(from, direction * span)
    const nextTo = addDays(to, direction * span)
    if (nextTo >= today) {
        // Back on the window that ends today: the relative preset shares the web's cache entry again.
        return origin && RANGE_PRESETS[origin].unit === 'days'
            ? presetChoice(origin)
            : fixedDays(addDays(today, 1 - span), today, 'days', origin)
    }
    return fixedDays(nextFrom, nextTo, 'days', origin)
}

function stepHours(
    resolved: ResolvedRange,
    direction: StepDirection,
    now: number,
    origin: RangePresetKey | null
): RangeChoice | null {
    const from = Date.parse(resolved.from)
    const to = Date.parse(resolved.to)
    if (Number.isNaN(from) || Number.isNaN(to) || to <= from) {
        return null
    }
    if (direction === 1 && to >= now - HOUR_TOLERANCE_MS) {
        return null
    }
    const length = to - from
    const nextTo = to + direction * length
    if (nextTo >= now - HOUR_TOLERANCE_MS) {
        return origin && RANGE_PRESETS[origin].unit === 'hours' ? presetChoice(origin) : null
    }
    return {
        kind: 'fixed',
        dateFrom: new Date(from + direction * length).toISOString(),
        dateTo: new Date(nextTo).toISOString(),
        explicitDate: true,
        unit: 'hours',
        origin,
    }
}

function sameChoice(next: RangeChoice, choice: RangeChoice | null, saved: SavedRange): boolean {
    if (next.kind === 'preset') {
        const current = choice
            ? choice.kind === 'preset'
                ? choice.key
                : null
            : presetForValues(saved.dateFrom, saved.dateTo)?.key
        return current === next.key
    }
    return choice?.kind === 'fixed' && choice.dateFrom === next.dateFrom && choice.dateTo === next.dateTo
}

/**
 * The choice one step back (-1) or forward (1) from the current one, or null when that step is not possible: All
 * time, forward from the window that holds now, no resolved window yet, or a step that lands on the range already
 * shown. A step that lands on the current period returns its relative preset (`dStart`, `wStart`, `mStart`, `yStart`,
 * or the original `-Nd`).
 */
export function stepRange(
    choice: RangeChoice | null,
    saved: SavedRange,
    direction: StepDirection,
    context: StepContext
): RangeChoice | null {
    const next = stepOf(choice, saved, direction, context)
    // An hours window resolves to the end of the hour of its compute, so a cached "Last 24 hours" read in an earlier
    // hour ends before now, and a step forward would only return the same preset.
    return next && !sameChoice(next, choice, saved) ? next : null
}

function stepOf(
    choice: RangeChoice | null,
    saved: SavedRange,
    direction: StepDirection,
    context: StepContext
): RangeChoice | null {
    const { resolved, today, now } = context
    const { unit, origin } = currentOf(choice, saved)
    if (!unit || !resolved) {
        return null
    }
    const from = resolved.from.slice(0, 10)
    const to = resolved.to.slice(0, 10)
    switch (unit) {
        case 'day':
            return stepDay(from, direction, today, origin)
        case 'week':
            return stepWeek(from, to, direction, today, origin)
        case 'month':
            return stepMonth(from, to, direction, today, origin)
        case 'year':
            return stepYear(from, to, direction, today, origin)
        case 'days':
            return stepDays(from, to, direction, today, origin)
        case 'hours':
            return stepHours(resolved, direction, now, origin)
    }
}
