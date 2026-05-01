import { RRule, Frequency } from 'rrule'

import { dayjs } from 'lib/dayjs'

export const ONE_TIME_RRULE = 'FREQ=DAILY;COUNT=1'

export function isOneTimeSchedule(rruleStr: string): boolean {
    try {
        const rule = RRule.fromString(rruleStr)
        return rule.options.count === 1
    } catch {
        return false
    }
}

export type FrequencyOption = 'daily' | 'weekly' | 'monthly' | 'yearly'
export type MonthlyMode = 'day_of_month' | 'nth_weekday' | 'last_day'
export type EndType = 'never' | 'on_date' | 'after_count'

export const FREQUENCY_OPTIONS: { value: FrequencyOption; label: string }[] = [
    { value: 'daily', label: 'Day' },
    { value: 'weekly', label: 'Week' },
    { value: 'monthly', label: 'Month' },
    { value: 'yearly', label: 'Year' },
]

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const WEEKDAY_PILL_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as const
export const WEEKDAY_RRULE_DAYS = [RRule.MO, RRule.TU, RRule.WE, RRule.TH, RRule.FR, RRule.SA, RRule.SU]
export const WEEKDAY_FULL_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export const NTH_LABELS = ['1st', '2nd', '3rd', '4th', '5th']

/** Default number of preview occurrences for open-ended (never-ending) schedules */
const DEFAULT_PREVIEW_COUNT = 6
/** Max preview occurrences for finite schedules (after count / on date) to avoid rendering huge lists */
const MAX_PREVIEW_COUNT = 200

export interface ScheduleState {
    interval: number
    frequency: FrequencyOption
    weekdays: number[] // 0=Mon, 6=Sun
    monthlyMode: MonthlyMode
    endType: EndType
    endDate: string | null
    endCount: number
}

export const DEFAULT_STATE: ScheduleState = {
    interval: 1,
    frequency: 'weekly',
    weekdays: [],
    monthlyMode: 'day_of_month',
    endType: 'never',
    endDate: null,
    endCount: 10,
}

export function frequencyToRRule(freq: FrequencyOption): Frequency {
    switch (freq) {
        case 'daily':
            return RRule.DAILY
        case 'weekly':
            return RRule.WEEKLY
        case 'monthly':
            return RRule.MONTHLY
        case 'yearly':
            return RRule.YEARLY
    }
}

/** Returns the nth occurrence of this weekday in the month (e.g. "3rd Wednesday"). */
export function getNthWeekdayOfMonth(date: dayjs.Dayjs): { n: number; weekday: number } {
    const dayOfMonth = date.date()
    // Convert from JS day (0=Sun) to rrule day (0=Mon)
    const weekday = (date.day() + 6) % 7
    const n = Math.ceil(dayOfMonth / 7)
    return { n, weekday }
}

export function parseRRuleToState(rruleStr: string): ScheduleState {
    try {
        const rule = RRule.fromString(rruleStr)
        const opts = rule.options

        let frequency: FrequencyOption = 'weekly'
        switch (opts.freq) {
            case RRule.DAILY:
                frequency = 'daily'
                break
            case RRule.WEEKLY:
                frequency = 'weekly'
                break
            case RRule.MONTHLY:
                frequency = 'monthly'
                break
            case RRule.YEARLY:
                frequency = 'yearly'
                break
        }

        const weekdays = opts.byweekday ? (opts.byweekday as number[]) : []

        let monthlyMode: MonthlyMode = 'day_of_month'
        if (frequency === 'monthly') {
            const origByMonthDay = rule.origOptions.bymonthday
            const hasLastDay = Array.isArray(origByMonthDay) ? origByMonthDay.includes(-1) : origByMonthDay === -1
            if (hasLastDay) {
                monthlyMode = 'last_day'
            } else if (opts.bysetpos && opts.bysetpos.length > 0) {
                monthlyMode = 'nth_weekday'
            }
        }

        let endType: EndType = 'never'
        let endDate: string | null = null
        let endCount = 10

        if (opts.until) {
            endType = 'on_date'
            endDate = dayjs(opts.until).toISOString()
        } else if (opts.count) {
            endType = 'after_count'
            endCount = opts.count
        }

        return { interval: opts.interval || 1, frequency, weekdays, monthlyMode, endType, endDate, endCount }
    } catch {
        return { ...DEFAULT_STATE }
    }
}

function buildRRuleOptions(
    state: ScheduleState,
    startsAt: string | null
): Partial<ConstructorParameters<typeof RRule>[0]> {
    const options: Partial<ConstructorParameters<typeof RRule>[0]> = {
        freq: frequencyToRRule(state.frequency),
        interval: state.interval,
    }

    if (state.frequency === 'weekly' && state.weekdays.length > 0) {
        options.byweekday = state.weekdays.map((d) => WEEKDAY_RRULE_DAYS[d])
    }

    if (state.frequency === 'monthly' && startsAt) {
        const date = dayjs(startsAt)
        if (state.monthlyMode === 'last_day') {
            options.bymonthday = [-1]
        } else if (state.monthlyMode === 'day_of_month') {
            options.bymonthday = [date.date()]
        } else {
            const { n, weekday } = getNthWeekdayOfMonth(date)
            options.byweekday = [WEEKDAY_RRULE_DAYS[weekday]]
            options.bysetpos = [n]
        }
    }

    if (state.endType === 'on_date' && state.endDate) {
        const d = dayjs(state.endDate)
        // End of day so the last occurrence on this date is included
        options.until = new Date(Date.UTC(d.year(), d.month(), d.date(), 23, 59, 59, 999))
    } else if (state.endType === 'after_count') {
        options.count = state.endCount
    }

    return options
}

export function stateToRRule(state: ScheduleState, startsAt: string | null): string {
    const options = buildRRuleOptions(state, startsAt)
    const rule = new RRule(options as ConstructorParameters<typeof RRule>[0])
    return rule.toString().replace('RRULE:', '')
}

/**
 * Generate preview dates for the occurrences list.
 * Interprets startsAt in the given timezone (or browser-local if omitted)
 * so the preview matches the actual execution times.
 */
export function computePreviewOccurrences(
    state: ScheduleState,
    startsAt: string,
    timezone?: string,
    count?: number
): Date[] {
    const limit =
        count ??
        (state.endType === 'after_count'
            ? Math.min(state.endCount, MAX_PREVIEW_COUNT)
            : state.endType === 'on_date'
              ? MAX_PREVIEW_COUNT
              : DEFAULT_PREVIEW_COUNT)
    try {
        // Parse startsAt in the schedule's timezone so the rrule expands
        // at the correct local time (e.g. "9 AM Prague" stays 9 AM across DST)
        const inScheduleTz = timezone ? dayjs(startsAt).tz(timezone) : dayjs(startsAt)
        const dtstart = new Date(
            Date.UTC(
                inScheduleTz.year(),
                inScheduleTz.month(),
                inScheduleTz.date(),
                inScheduleTz.hour(),
                inScheduleTz.minute(),
                0
            )
        )

        const options = buildRRuleOptions(state, startsAt)!
        options.dtstart = dtstart

        const rule = new RRule(options as ConstructorParameters<typeof RRule>[0])
        const isFinite = state.endType !== 'never'

        if (dayjs(dtstart).isBefore(dayjs())) {
            const all = rule.all((_, i) => i < (isFinite ? MAX_PREVIEW_COUNT : limit * 50))
            const now = new Date()
            const future = all.filter((d) => d.getTime() > now.getTime())
            return isFinite ? future : future.slice(0, limit)
        }
        return rule.all((_, i) => i < (isFinite ? MAX_PREVIEW_COUNT : limit))
    } catch {
        return []
    }
}

/**
 * Convert a "fake UTC" date (where UTC values represent local time in the schedule
 * timezone, as produced by computePreviewOccurrences/rrule) to a real timestamp.
 *
 * RRule expands dates using UTC values that actually represent local times in the
 * schedule timezone. This function reinterprets those values as real moments in time.
 * For example, a fake-UTC date of 2026-04-03T19:25:00Z representing 19:25 Europe/Riga
 * becomes 2026-04-03T16:25:00Z (the actual UTC moment).
 */
export function fakeUtcToReal(date: Date, timezone?: string): dayjs.Dayjs {
    const utcStr = dayjs(date).utc().format('YYYY-MM-DD HH:mm:ss')
    return timezone ? dayjs.tz(utcStr, timezone) : dayjs.utc(utcStr)
}

export function buildSummary(state: ScheduleState, startsAt: string | null): string {
    const freqLabel = state.frequency === 'daily' ? 'day' : state.frequency.replace('ly', '')
    const intervalStr = state.interval > 1 ? `${state.interval} ${freqLabel}s` : freqLabel

    let summary = `Runs every ${intervalStr}`

    if (state.frequency === 'weekly' && state.weekdays.length > 0) {
        const dayNames = state.weekdays.map((d) => WEEKDAY_FULL_LABELS[d])
        summary += ` on ${dayNames.join(', ')}`
    }

    if (state.frequency === 'monthly') {
        if (state.monthlyMode === 'last_day') {
            summary += ` on the last day`
        } else if (state.monthlyMode === 'day_of_month' && startsAt) {
            summary += ` on the ${dayjs(startsAt).format('Do')}`
        } else if (state.monthlyMode === 'nth_weekday' && startsAt) {
            const { n, weekday } = getNthWeekdayOfMonth(dayjs(startsAt))
            summary += ` on the ${NTH_LABELS[n - 1]} ${WEEKDAY_FULL_LABELS[weekday]}`
        }
    }

    if (startsAt) {
        summary += `, starting ${dayjs(startsAt).format('MMMM D')}`
    }

    if (state.endType === 'after_count') {
        summary += `, ${state.endCount} times`
    } else if (state.endType === 'on_date' && state.endDate) {
        summary += `, until ${dayjs(state.endDate).format('MMMM D, YYYY')}`
    }

    return summary + '.'
}

/** Parse natural language like "every week on Monday and Wednesday" into a ScheduleState. */
export function parseNaturalLanguage(text: string): ScheduleState | null {
    const trimmed = text.trim().toLowerCase()
    if (!trimmed || !trimmed.includes('every')) {
        return null
    }
    try {
        const rule = RRule.fromText(text)
        if (!rule || rule.options.freq == null) {
            return null
        }
        const rruleStr = rule.toString().replace('RRULE:', '')
        return parseRRuleToState(rruleStr)
    } catch {
        return null
    }
}

/** Convert a ScheduleState to a human-readable text like "every week on Monday, Wednesday". */
export function scheduleToText(state: ScheduleState, startsAt: string | null): string {
    try {
        const options = buildRRuleOptions(state, startsAt)
        const rule = new RRule(options as ConstructorParameters<typeof RRule>[0])
        return rule.toText()
    } catch {
        return ''
    }
}
