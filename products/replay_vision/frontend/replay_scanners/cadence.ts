// Cadence helpers for the vision-action create/edit form.
//
// Self-contained — we only need a set of weekdays + a time of day, not the full
// recurring machinery (interval, monthly modes, end conditions) that the Workflows
// RecurringSchedulePicker offers. The Workflows backend made the same copy-not-import
// call for its rrule date math (see products/replay_vision/backend/rrule.py).
//
// The schedule is expressed as the days of the week it runs on: pick a subset for a
// weekly cadence, or all seven for a daily one. There is no separate daily/weekly mode —
// the frequency is implied by how many days are selected, and all seven normalizes to
// FREQ=DAILY. At least one day must be selected (enforced by the form).
//
// The backend's trigger_config is only { rrule, timezone } with no DTSTART — the
// scheduler derives starts_at from the action's created_at, so the run time of day must
// live in the rrule itself via BYHOUR/BYMINUTE (dateutil honors those over the dtstart
// time component).

export interface CadenceState {
    /** Days of week the action runs on. 0=Mon … 6=Sun. Must contain at least one; all seven = daily. */
    weekdays: number[]
    /** Hour of day, 0–23, in the action's timezone. */
    hour: number
    /** Minute of hour, 0–59. */
    minute: number
}

// 0=Mon … 6=Sun, matching CadenceState.weekdays.
const ALL_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]
const RRULE_DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const
const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

export const DEFAULT_CADENCE: CadenceState = {
    weekdays: [...ALL_WEEKDAYS],
    hour: 9,
    minute: 0,
}

function pad2(n: number): string {
    return n.toString().padStart(2, '0')
}

function sortedWeekdays(weekdays: number[]): number[] {
    return [...weekdays].sort((a, b) => a - b)
}

export function cadenceToRrule(state: CadenceState): string {
    const isDaily = state.weekdays.length === 7
    const parts = [`FREQ=${isDaily ? 'DAILY' : 'WEEKLY'}`]
    if (!isDaily && state.weekdays.length > 0) {
        parts.push(
            `BYDAY=${sortedWeekdays(state.weekdays)
                .map((d) => RRULE_DAYS[d])
                .join(',')}`
        )
    }
    parts.push(`BYHOUR=${state.hour}`, `BYMINUTE=${state.minute}`)
    return parts.join(';')
}

function parseWeekdays(rrule: string): number[] {
    const byday = /BYDAY=([A-Z,]+)/.exec(rrule)?.[1]
    if (!byday) {
        return []
    }
    return byday
        .split(',')
        .map((d) => RRULE_DAYS.indexOf(d.trim() as (typeof RRULE_DAYS)[number]))
        .filter((i) => i >= 0)
        .sort((a, b) => a - b)
}

function parseClampedInt(rrule: string, key: string, max: number, fallback: number): number {
    const raw = new RegExp(`${key}=(\\d+)`).exec(rrule)?.[1]
    if (raw === undefined) {
        return fallback
    }
    const value = parseInt(raw, 10)
    return Number.isNaN(value) || value < 0 || value > max ? fallback : value
}

export function parseRruleToCadence(rrule: string | undefined | null): CadenceState {
    const freq = rrule ? /FREQ=([A-Z]+)/.exec(rrule)?.[1] : undefined
    // Only DAILY/WEEKLY are produced by this form; anything else (legacy monthly, yearly,
    // empty) falls back to the default daily cadence.
    if (freq !== 'DAILY' && freq !== 'WEEKLY') {
        return { ...DEFAULT_CADENCE }
    }
    const hour = parseClampedInt(rrule!, 'BYHOUR', 23, DEFAULT_CADENCE.hour)
    const minute = parseClampedInt(rrule!, 'BYMINUTE', 59, DEFAULT_CADENCE.minute)
    if (freq === 'DAILY') {
        return { weekdays: [...ALL_WEEKDAYS], hour, minute }
    }
    // Weekly with no BYDAY is a legacy "every day" — normalize to all seven.
    const weekdays = parseWeekdays(rrule!)
    return { weekdays: weekdays.length > 0 ? weekdays : [...ALL_WEEKDAYS], hour, minute }
}

export function humanizeCadence(state: CadenceState): string {
    const time = `${pad2(state.hour)}:${pad2(state.minute)}`
    if (state.weekdays.length === 0) {
        return 'Pick at least one day'
    }
    if (state.weekdays.length === 7) {
        return `Daily at ${time}`
    }
    const days = sortedWeekdays(state.weekdays)
        .map((d) => WEEKDAY_SHORT[d])
        .join(', ')
    return `Weekly on ${days} at ${time}`
}
