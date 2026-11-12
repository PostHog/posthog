import { Dayjs, dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

// The longest a person can wait: the longest frequency cap hold, or a slow send on a low sending limit.
const STILL_SENDING_WINDOW_DAYS = 7

export const RUN_AUDIENCE_METRICS = [
    'triggered',
    'email_sent',
    'failed',
    'email_opted_out',
    'email_suppressed',
    'email_missing_recipient',
    'email_bounce_prevented',
    'message_frequency_cap_held',
    'message_frequency_cap_hold_ended',
    'message_frequency_capped',
    'filtered',
    'early_exit',
]

/** A run with no send activity for this long has nobody left to send to. */
export function canStillBeSending(lastActivityAt: string, now: Dayjs = dayjs()): boolean {
    return now.diff(dayjs(lastActivityAt), 'day', true) <= STILL_SENDING_WINDOW_DAYS
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
    filteredOut: number
    exitedEarly: number
    stillSending: boolean
}

export function getRunAudience(
    totals: Record<string, number> | null | undefined,
    lastActivityAt: string,
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
    // Only step failures: `email_failed` also counts rejects that SES reports after the send.
    const failed = count('failed')
    const filteredOut = count('filtered')
    const exitedEarly = count('early_exit')
    const unfinished = Math.max(
        audience - sent - optedOut - suppressed - skippedAtCap - noEmail - failed - filteredOut - exitedEarly,
        0
    )
    const withinWindow = canStillBeSending(lastActivityAt, now)
    const stillHeld = Math.max(count('message_frequency_cap_held') - count('message_frequency_cap_hold_ended'), 0)
    const waitingOnCap = withinWindow ? Math.min(unfinished, stillHeld) : 0
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
        filteredOut,
        exitedEarly,
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
        [run.filteredOut, "skipped by the email step's filters"],
        [run.exitedEarly, 'left early because of the exit condition'],
        [run.failed, 'failed'],
    ]
    const shown = parts.filter(([count]) => count > 0).map(([count, label]) => `${humanFriendlyNumber(count)} ${label}`)
    return `${humanFriendlyNumber(run.audience)} in audience: ${shown.join(', ') || 'nothing sent yet'}`
}
