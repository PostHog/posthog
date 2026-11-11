import { Dayjs, dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

// Runs that started before this date recorded opt-outs in logs only, so their opt-outs read as not sent.
const OPT_OUTS_COUNTED_SINCE = dayjs('2026-11-20T00:00:00Z')
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
    const audience = totals?.triggered ?? 0
    if (!totals || audience <= 0) {
        return null
    }
    const sent = totals.email_sent ?? 0
    const optedOut = totals.email_opted_out ?? 0
    const suppressed = totals.email_suppressed ?? 0
    const skippedAtCap = totals.message_frequency_capped ?? 0
    const noEmail = (totals.email_missing_recipient ?? 0) + (totals.email_bounce_prevented ?? 0)
    // A send that errors can record both metrics for one person.
    const failed = Math.max(totals.email_failed ?? 0, totals.failed ?? 0)
    const unfinished = Math.max(audience - sent - optedOut - suppressed - skippedAtCap - noEmail - failed, 0)
    // The held count never goes down, so someone who was held and later sent is only out of `unfinished`.
    const waitingOnCap = Math.min(unfinished, totals.message_frequency_cap_held ?? 0)
    const remaining = unfinished - waitingOnCap

    const started = dayjs(runStartedAt)
    const withinWindow = now.diff(started, 'day', true) <= STILL_SENDING_WINDOW_DAYS
    const countsOptOuts = !started.isBefore(OPT_OUTS_COUNTED_SINCE)
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
        stillSending: withinWindow && (waitingOnCap > 0 || (countsOptOuts && remaining > 0)),
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
