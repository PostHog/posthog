// Cadence helpers for the vision-action create/edit form.
//
// Self-contained — we only need daily/weekly/monthly + a time of day, not the full
// recurring machinery (interval, monthly modes, end conditions) that the Workflows
// RecurringSchedulePicker offers. The Workflows backend made the same copy-not-import
// call for its rrule date math (see products/replay_vision/backend/rrule.py).
//
// The backend's trigger_config is only { rrule, timezone } with no DTSTART — the
// scheduler derives starts_at from the action's created_at, so the run time of day must
// live in the rrule itself via BYHOUR/BYMINUTE (dateutil honors those over the dtstart
// time component).

export type CadenceFrequency = 'daily' | 'weekly' | 'monthly'

export interface CadenceState {
    frequency: CadenceFrequency
    /** Days of week for weekly cadence. 0=Mon … 6=Sun. Ignored for daily/monthly. */
    weekdays: number[]
    /** Hour of day, 0–23, in the action's timezone. */
    hour: number
    /** Minute of hour, 0–59. */
    minute: number
}

export const DEFAULT_CADENCE: CadenceState = {
    frequency: 'daily',
    weekdays: [],
    hour: 9,
    minute: 0,
}

// 0=Mon … 6=Sun, matching CadenceState.weekdays.
const RRULE_DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const
const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

const FREQ_BY_CADENCE: Record<CadenceFrequency, string> = {
    daily: 'DAILY',
    weekly: 'WEEKLY',
    monthly: 'MONTHLY',
}

function pad2(n: number): string {
    return n.toString().padStart(2, '0')
}

export function cadenceToRrule(state: CadenceState): string {
    const parts = [`FREQ=${FREQ_BY_CADENCE[state.frequency]}`]
    if (state.frequency === 'weekly' && state.weekdays.length > 0) {
        const days = [...state.weekdays].sort((a, b) => a - b).map((d) => RRULE_DAYS[d])
        parts.push(`BYDAY=${days.join(',')}`)
    }
    parts.push(`BYHOUR=${state.hour}`, `BYMINUTE=${state.minute}`)
    return parts.join(';')
}

function parseFrequency(rrule: string): CadenceFrequency | null {
    const freq = /FREQ=([A-Z]+)/.exec(rrule)?.[1]
    switch (freq) {
        case 'DAILY':
            return 'daily'
        case 'WEEKLY':
            return 'weekly'
        case 'MONTHLY':
            return 'monthly'
        default:
            return null
    }
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
    if (!rrule) {
        return { ...DEFAULT_CADENCE }
    }
    const frequency = parseFrequency(rrule)
    if (!frequency) {
        return { ...DEFAULT_CADENCE }
    }
    return {
        frequency,
        weekdays: frequency === 'weekly' ? parseWeekdays(rrule) : [],
        hour: parseClampedInt(rrule, 'BYHOUR', 23, DEFAULT_CADENCE.hour),
        minute: parseClampedInt(rrule, 'BYMINUTE', 59, DEFAULT_CADENCE.minute),
    }
}

export function humanizeCadence(state: CadenceState): string {
    const time = `${pad2(state.hour)}:${pad2(state.minute)}`
    if (state.frequency === 'weekly') {
        const days =
            state.weekdays.length > 0
                ? [...state.weekdays]
                      .sort((a, b) => a - b)
                      .map((d) => WEEKDAY_SHORT[d])
                      .join(', ')
                : 'every day'
        return `Weekly on ${days} at ${time}`
    }
    const label = state.frequency === 'daily' ? 'Daily' : 'Monthly'
    return `${label} at ${time}`
}
