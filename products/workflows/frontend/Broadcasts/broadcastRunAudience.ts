import { Dayjs, dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

// The longest a person can wait: the longest frequency cap hold, or a slow send on a low sending limit.
const STILL_SENDING_WINDOW_DAYS = 7

export const RUN_AUDIENCE_METRICS = [
    'triggered',
    'email_sent',
    'email_failed',
    'failed',
    'email_opted_out',
    'email_suppressed',
    'email_missing_recipient',
    'email_bounce_prevented',
    'message_frequency_cap_held',
    'message_frequency_capped',
]

/** Runs older than this can't have anyone left to send to, so they never need their metrics to show a status. */
export function canStillBeSending(runStartedAt: string, now: Dayjs = dayjs()): boolean {
    return now.diff(dayjs(runStartedAt), 'day', true) <= STILL_SENDING_WINDOW_DAYS
}

export interface RunAudience {
    audience: number
    sent: number
    waitingOnCap: number
    /** People nothing has happened to yet, or that this run can no longer account for. */
    remaining: number
    optedOut: number
    suppressed: number
    skippedAtCap: number
    noEmail: number
    failed: number
    stillSending: boolean
}

export function getRunAudience(
    totals: Record<string, number> | null | undefined,
    runStartedAt: string,
    now: Dayjs = dayjs()
): RunAudience | null {
    if (!totals || !(totals.triggered > 0)) {
        return null
    }
    const count = (metric: string): number => totals[metric] ?? 0
    const audience = count('triggered')
    const sent = count('email_sent')
    const optedOut = count('email_opted_out')
    const suppressed = count('email_suppressed')
    const skippedAtCap = count('message_frequency_capped')
    const noEmail = count('email_missing_recipient') + count('email_bounce_prevented')
    // A send that errors can record both metrics for one person.
    const failed = Math.max(count('email_failed'), count('failed'))
    const unfinished = Math.max(audience - sent - optedOut - suppressed - skippedAtCap - noEmail - failed, 0)
    const withinWindow = canStillBeSending(runStartedAt, now)
    // The held count never goes down, so someone who was held and later sent is only out of `unfinished`.
    const waitingOnCap = withinWindow ? Math.min(unfinished, count('message_frequency_cap_held')) : 0
    const remaining = unfinished - waitingOnCap

    return {
        audience,
        sent,
        waitingOnCap,
        remaining,
        optedOut,
        suppressed,
        skippedAtCap,
        noEmail,
        failed,
        stillSending: withinWindow && (waitingOnCap > 0 || remaining > 0),
    }
}

export function describeRunAudience(run: RunAudience): string {
    const parts: [number, string][] = [
        [run.sent, 'sent'],
        [run.waitingOnCap, 'waiting on the frequency cap'],
        [run.remaining, run.stillSending ? 'still to send' : 'not sent'],
        [run.optedOut, 'opted out'],
        [run.suppressed, 'on the suppression list'],
        [run.skippedAtCap, 'skipped by the frequency cap'],
        [run.noEmail, 'with no usable email address'],
        [run.failed, 'failed'],
    ]
    const shown = parts.filter(([count]) => count > 0).map(([count, label]) => `${humanFriendlyNumber(count)} ${label}`)
    return `${humanFriendlyNumber(run.audience)} in audience: ${shown.join(', ') || 'nothing sent yet'}`
}
