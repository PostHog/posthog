import { dayjs } from 'lib/dayjs'

import type { CalendarSend, SendAudience } from './sendCalendarUtils'

/** The most marketing emails that one person gets in a window of days. */
export interface SendingRule {
    maxMessages: number
    windowDays: number
    /** False when the project has no frequency cap, so the rule is the default spacing. */
    fromCap: boolean
}

// Without a frequency cap, the suggestions keep marketing sends to the same people at least 2 days apart.
const DEFAULT_RULE: SendingRule = { maxMessages: 1, windowDays: 2, fromCap: false }
export const SUGGESTION_HORIZON_DAYS = 60
// The broadcast editor rejects a send time in the past, so a suggestion for today leaves a margin.
const SUGGESTION_LEAD_MINUTES = 15

export function sendingRule(
    config:
        | {
              marketing_frequency_cap_max_messages?: number | null
              marketing_frequency_cap_window_days?: number | null
          }
        | null
        | undefined
): SendingRule {
    const maxMessages = config?.marketing_frequency_cap_max_messages
    const windowDays = config?.marketing_frequency_cap_window_days
    return maxMessages && windowDays ? { maxMessages, windowDays, fromCap: true } : DEFAULT_RULE
}

export function describeRule(rule: SendingRule): string {
    const emails = `${rule.maxMessages} marketing ${rule.maxMessages === 1 ? 'email' : 'emails'}`
    return `${emails} per person every ${rule.windowDays} ${rule.windowDays === 1 ? 'day' : 'days'}`
}

/**
 * Whether two audiences can hold the same people. Without a count of the shared people, only two
 * audiences of cohorts with no cohort in common count as apart.
 */
export function mayShareRecipients(a: SendAudience, b: SendAudience): boolean {
    const cohortsOnly = (audience: SendAudience): boolean =>
        audience.cohortIds.length > 0 && audience.filters.length === 0
    if (!cohortsOnly(a) || !cohortsOnly(b)) {
        return true
    }
    return a.cohortIds.some((id) => b.cohortIds.includes(id))
}

/**
 * Whether another send counts against a new send to `audience`, as the frequency cap counts it at send
 * time: a send to a fixed address has no person to count. The calendar endpoint already leaves out
 * transactional email, which the cap never counts.
 */
export function countsTowardRule(send: Pick<CalendarSend, 'audience'>, audience: SendAudience): boolean {
    return !send.audience.address && mayShareRecipients(audience, send.audience)
}

/**
 * The sends that would give someone more than the rule allows if a new send goes out at `at`, or an
 * empty list when `at` is fine. The cap counts the sends in a rolling window, so every window of
 * `windowDays` that holds `at` must stay at `maxMessages` or below, the new send included.
 */
export function crowdingSends<T extends { at: dayjs.Dayjs }>(at: dayjs.Dayjs, others: T[], rule: SendingRule): T[] {
    const windowMs = rule.windowDays * 24 * 60 * 60 * 1000
    const near = others
        .filter((send) => Math.abs(send.at.valueOf() - at.valueOf()) < windowMs)
        .sort((a, b) => a.at.valueOf() - b.at.valueOf())
    // The fullest window that holds `at` starts at `at` or at one of the earlier sends near it.
    const starts = [at.valueOf(), ...near.filter((send) => send.at.isBefore(at)).map((send) => send.at.valueOf())]
    for (const start of starts) {
        const inWindow = near.filter((send) => send.at.valueOf() >= start && send.at.valueOf() < start + windowMs)
        if (inWindow.length + 1 > rule.maxMessages) {
            return inWindow
        }
    }
    return []
}

/** A time of day ("HH:mm:ss") on a calendar day ("YYYY-MM-DD"), in a time zone. */
export function timeOnDay(day: string, timeOfDay: string, timezone: string): dayjs.Dayjs {
    return dayjs.tz(`${day} ${timeOfDay}`, timezone)
}

/** The first day, from today, where a send at `timeOfDay` keeps everyone within the rule. */
export function suggestSendTime<T extends { at: dayjs.Dayjs }>({
    timeOfDay,
    timezone,
    now,
    others,
    rule,
}: {
    timeOfDay: string
    timezone: string
    now: dayjs.Dayjs
    others: T[]
    rule: SendingRule
}): dayjs.Dayjs | null {
    const earliest = now.add(SUGGESTION_LEAD_MINUTES, 'minute')
    // Calendar days have no time zone, so the day arithmetic runs in UTC, where every day has 24 hours.
    const firstDay = dayjs.utc(now.tz(timezone).format('YYYY-MM-DD'))
    for (let offset = 0; offset <= SUGGESTION_HORIZON_DAYS; offset++) {
        const at = timeOnDay(firstDay.add(offset, 'day').format('YYYY-MM-DD'), timeOfDay, timezone)
        if (at.isAfter(earliest) && crowdingSends(at, others, rule).length === 0) {
            return at
        }
    }
    return null
}
