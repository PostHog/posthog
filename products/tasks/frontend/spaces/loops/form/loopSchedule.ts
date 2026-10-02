import type { LoopScheduleTriggerConfig } from './loopFormValues'

// Mirrors PostHog Desktop's `loopCron.ts`, `nextRecurringRun.ts` and `loopScheduleRRule.ts`, so both apps read
// and write the same schedule shapes.

export type RecurringFrequency = 'hourly' | 'daily' | 'weekdays' | 'weekly'

export interface RecurringSchedule {
    frequency: RecurringFrequency
    /** `HH:MM`, 24-hour. */
    time: string
    /** "0" (Sunday) to "6" (Saturday), as in cron. */
    weekday: string
}

export interface HogFlowScheduleWrite {
    rrule: string
    starts_at: string
    timezone: string
}

export const DEFAULT_SCHEDULE_TIME = '09:00'

/**
 * Reads the cron shapes the frequency picker writes. Anything else (step values, day of month, day lists)
 * returns null and shows as a custom schedule, so it is never quietly rewritten into a picker shape.
 */
export function parseCronSchedule(cron: string | null | undefined): RecurringSchedule | null {
    if (!cron) {
        return null
    }
    const parts = cron.trim().split(/\s+/)
    if (parts.length !== 5) {
        return null
    }
    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts
    if (dayOfMonth !== '*' || month !== '*' || !/^\d{1,2}$/.test(minute) || Number(minute) > 59) {
        return null
    }
    if (hour === '*') {
        return minute === '0' && dayOfWeek === '*'
            ? { frequency: 'hourly', time: DEFAULT_SCHEDULE_TIME, weekday: '1' }
            : null
    }
    if (!/^\d{1,2}$/.test(hour) || Number(hour) > 23) {
        return null
    }
    const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
    if (dayOfWeek === '*') {
        return { frequency: 'daily', time, weekday: '1' }
    }
    if (dayOfWeek === '1-5') {
        return { frequency: 'weekdays', time, weekday: '1' }
    }
    if (/^[0-6]$/.test(dayOfWeek)) {
        return { frequency: 'weekly', time, weekday: dayOfWeek }
    }
    return null
}

export function compileCronSchedule(frequency: RecurringFrequency, time: string, weekday: string): string {
    const [hourPart, minutePart] = time.split(':')
    const hour = Number(hourPart) || 0
    const minute = Number(minutePart) || 0
    switch (frequency) {
        case 'hourly':
            return '0 * * * *'
        case 'daily':
            return `${minute} ${hour} * * *`
        case 'weekdays':
            return `${minute} ${hour} * * 1-5`
        case 'weekly':
            return `${minute} ${hour} * * ${weekday}`
    }
}

const WEEKDAY_BY_SHORT_NAME: Record<string, string> = {
    Sun: '0',
    Mon: '1',
    Tue: '2',
    Wed: '3',
    Thu: '4',
    Fri: '5',
    Sat: '6',
}

function wallClockFormatter(timezone: string): Intl.DateTimeFormat | null {
    try {
        return new Intl.DateTimeFormat('en-US', {
            timeZone: timezone,
            hourCycle: 'h23',
            hour: '2-digit',
            minute: '2-digit',
            weekday: 'short',
        })
    } catch {
        return null
    }
}

interface WallClock {
    hour: number
    minute: number
    weekday: string
}

/** The clock time and weekday of an instant in a timezone, or null when either cannot be read. */
function wallClock(instant: string | Date, timezone: string): WallClock | null {
    const date = new Date(instant)
    const formatter = wallClockFormatter(timezone)
    if (Number.isNaN(date.getTime()) || !formatter) {
        return null
    }
    const parts = formatter.formatToParts(date)
    const read = (type: string): string | undefined => parts.find((part) => part.type === type)?.value
    const hour = read('hour')
    const minute = read('minute')
    const weekday = WEEKDAY_BY_SHORT_NAME[read('weekday') ?? '']
    if (!hour || !minute || !weekday) {
        return null
    }
    // Some engines render midnight as "24" under h23.
    return { hour: hour === '24' ? 0 : Number(hour), minute: Number(minute), weekday }
}

/** The next time a recurring schedule fires after `now`, in the schedule's timezone. */
export function nextRecurringRun(schedule: RecurringSchedule, timezone: string, now = new Date()): Date | null {
    if (!wallClockFormatter(timezone)) {
        return null
    }
    const [targetHour, targetMinute] = schedule.time.split(':').map(Number)
    let candidateMs = Math.floor(now.getTime() / 60_000) * 60_000 + 60_000
    for (let iteration = 0; iteration < 8 * 24 + 2; iteration += 1) {
        const clock = wallClock(new Date(candidateMs), timezone)
        if (!clock) {
            return null
        }
        const minuteAdjustment = (targetMinute - clock.minute + 60) % 60
        if (minuteAdjustment > 0) {
            candidateMs += minuteAdjustment * 60_000
            continue
        }
        const matchesHour = schedule.frequency === 'hourly' || clock.hour === targetHour
        const matchesWeekday = schedule.frequency !== 'weekdays' || (clock.weekday !== '0' && clock.weekday !== '6')
        const matchesWeekly = schedule.frequency !== 'weekly' || clock.weekday === schedule.weekday
        if (matchesHour && matchesWeekday && matchesWeekly) {
            return new Date(candidateMs)
        }
        candidateMs += 60 * 60_000
    }
    return null
}

/** The next run of a schedule trigger, or null for a custom cron or a one-time run in the past. */
export function nextScheduleRun(config: LoopScheduleTriggerConfig, now = new Date()): Date | null {
    if (config.run_at) {
        const runAt = new Date(config.run_at)
        return runAt > now ? runAt : null
    }
    const schedule = parseCronSchedule(config.cron_expression)
    return schedule ? nextRecurringRun(schedule, config.timezone ?? 'UTC', now) : null
}

/** A date and time in a timezone, short enough for a table cell. */
export function formatScheduleTime(date: Date, timezone: string): string {
    try {
        return new Intl.DateTimeFormat(undefined, {
            timeZone: timezone,
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZoneName: 'short',
        }).format(date)
    } catch {
        return date.toLocaleString()
    }
}

const WEEKDAY_CODES = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'] as const
const WORKWEEK = 'MO,TU,WE,TH,FR'
/** The string the workflow editor writes for a one-time schedule. */
const ONE_TIME_RRULE = 'FREQ=DAILY;COUNT=1'
/** Any other key means someone edited the rule outside the loop form, so no preset describes it. */
const KNOWN_RRULE_KEYS = new Set(['FREQ', 'INTERVAL', 'COUNT', 'BYDAY', 'WKST'])

function presetRRule(frequency: RecurringFrequency, weekday: string): string {
    switch (frequency) {
        case 'hourly':
            return 'FREQ=HOURLY;INTERVAL=1'
        case 'daily':
            return 'FREQ=DAILY;INTERVAL=1'
        case 'weekdays':
            return `FREQ=WEEKLY;INTERVAL=1;BYDAY=${WORKWEEK}`
        case 'weekly':
            return `FREQ=WEEKLY;INTERVAL=1;BYDAY=${WEEKDAY_CODES[Number(weekday)]}`
    }
}

/**
 * The loop form's schedule as a workflow schedule row: the rule carries the frequency and the weekdays, and
 * `starts_at` carries the time of day, the way the workflow editor writes it. Returns null for a cron the
 * picker cannot express, so a save never drops part of the cadence.
 */
export function scheduleConfigToHogFlowSchedule(
    config: LoopScheduleTriggerConfig,
    now = new Date()
): HogFlowScheduleWrite | null {
    const timezone = config.timezone ?? 'UTC'
    if (config.run_at) {
        return { rrule: ONE_TIME_RRULE, starts_at: config.run_at, timezone }
    }
    const schedule = parseCronSchedule(config.cron_expression)
    const startsAt = schedule ? nextRecurringRun(schedule, timezone, now) : null
    if (!schedule || !startsAt) {
        return null
    }
    return { rrule: presetRRule(schedule.frequency, schedule.weekday), starts_at: startsAt.toISOString(), timezone }
}

function parseRRule(rrule: string): Map<string, string> | null {
    const parts = new Map<string, string>()
    for (const segment of rrule.split(';')) {
        if (!segment.trim()) {
            continue
        }
        const [key, value, ...rest] = segment.split('=')
        if (!key || value === undefined || rest.length) {
            return null
        }
        parts.set(key.trim().toUpperCase(), value.trim().toUpperCase())
    }
    return parts
}

/**
 * A workflow schedule row as the loop form's schedule. Returns null for a rule the form would not write, which
 * marks the loop as changed outside the form instead of guessing a nearby preset.
 */
export function hogFlowScheduleToScheduleConfig(schedule: {
    rrule: string
    starts_at: string
    timezone?: string | null
}): LoopScheduleTriggerConfig | null {
    const parts = parseRRule(schedule.rrule)
    if (!parts || [...parts.keys()].some((key) => !KNOWN_RRULE_KEYS.has(key))) {
        return null
    }
    if ((parts.get('INTERVAL') ?? '1') !== '1') {
        return null
    }
    const timezone = schedule.timezone ?? 'UTC'
    const freq = parts.get('FREQ')
    const byDay = parts.get('BYDAY')
    if (parts.has('COUNT')) {
        return parts.get('COUNT') === '1' && freq === 'DAILY' && !byDay
            ? { run_at: schedule.starts_at, timezone }
            : null
    }
    const clock = wallClock(schedule.starts_at, timezone)
    if (!clock) {
        return null
    }
    const cronTime = `${clock.minute} ${clock.hour}`
    if (freq === 'HOURLY') {
        // The hourly preset runs on the hour, so an anchor at :30 is not "hourly" in the picker's terms.
        return byDay || clock.minute !== 0 ? null : { cron_expression: '0 * * * *', timezone }
    }
    if (freq === 'DAILY') {
        return byDay ? null : { cron_expression: `${cronTime} * * *`, timezone }
    }
    if (freq === 'WEEKLY') {
        if (byDay === WORKWEEK) {
            return { cron_expression: `${cronTime} * * 1-5`, timezone }
        }
        // No BYDAY means the weekday of `starts_at`, which is how the editor stores a weekly rule before a day is picked.
        if (!byDay) {
            return { cron_expression: `${cronTime} * * ${clock.weekday}`, timezone }
        }
        const weekday = WEEKDAY_CODES.indexOf(byDay as (typeof WEEKDAY_CODES)[number])
        return weekday === -1 ? null : { cron_expression: `${cronTime} * * ${weekday}`, timezone }
    }
    return null
}

/**
 * Whether a schedule row already holds the cadence. It compares the clock time, not the instant, because
 * rewriting `starts_at` makes the scheduler recompute the next run and can skip one that was about to fire.
 */
export function hogFlowScheduleMatches(
    existing: { rrule: string; starts_at: string; timezone?: string | null },
    desired: HogFlowScheduleWrite
): boolean {
    const timezone = existing.timezone ?? 'UTC'
    if (existing.rrule !== desired.rrule || timezone !== desired.timezone) {
        return false
    }
    if (desired.rrule === ONE_TIME_RRULE) {
        return new Date(existing.starts_at).getTime() === new Date(desired.starts_at).getTime()
    }
    const before = wallClock(existing.starts_at, timezone)
    const after = wallClock(desired.starts_at, timezone)
    if (!before || !after || before.minute !== after.minute) {
        return false
    }
    return parseRRule(desired.rrule)?.get('FREQ') === 'HOURLY' || before.hour === after.hour
}
