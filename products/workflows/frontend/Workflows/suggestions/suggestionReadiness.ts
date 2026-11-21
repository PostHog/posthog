import { Dayjs, dayjs } from 'lib/dayjs'

import type { HogFlowOptimizationApi } from '../../generated/api.schemas'

export const MIN_VERSION_AGE_HOURS = 48
// Past this, an overdue check is likely stuck, so the page stops promising one.
const OVERDUE_GRACE_HOURS = 6

export type ReadinessStepState = 'done' | 'waiting' | 'blocked'

export interface ReadinessStep {
    key: 'enabled' | 'age' | 'sends' | 'check'
    title: string
    state: ReadinessStepState
    detail: string
    // 0 to 100 while the step fills up over time or sends, null when it has no measure.
    percent: number | null
}

export interface SuggestionReadiness {
    headline: string
    detail: string | null
    steps: ReadinessStep[]
}

function formatMoment(moment: Dayjs, now: Dayjs, preposition: 'at' | 'around'): string {
    const time = moment.format('h:mm A')
    if (moment.isSame(now, 'day')) {
        return `today ${preposition} ${time}`
    }
    if (moment.isSame(now.add(1, 'day'), 'day')) {
        return `tomorrow ${preposition} ${time}`
    }
    return `${moment.format('ddd, MMM D')} ${preposition} ${time}`
}

function trackedEmails(count: number): string {
    return `${count === 1 ? 'email' : 'emails'} with open tracking`
}

// A paused, dry-run, or missing scout never checks, and a workflow that can't turn suggestions on never gets there.
export function showSuggestionReadiness(
    optimization: HogFlowOptimizationApi | null,
    turnOnDisabledReason: string | undefined
): optimization is HogFlowOptimizationApi {
    if (!optimization) {
        return false
    }
    if (!optimization.enabled) {
        return !turnOnDisabledReason && ['running', 'not_running'].includes(optimization.scout_status)
    }
    return optimization.scout_status === 'running'
}

export function suggestionReadiness(
    optimization: HogFlowOptimizationApi | null,
    now: Dayjs = dayjs()
): SuggestionReadiness | null {
    if (!optimization) {
        return null
    }
    const { enabled, sample, schedule } = optimization
    const steps: ReadinessStep[] = []
    if (!enabled) {
        steps.push({
            key: 'enabled',
            title: 'Suggestions are on',
            state: 'blocked',
            detail: 'Turn on "Suggest improvements".',
            percent: null,
        })
    }

    let readyAt: Dayjs | null = null
    let sendsShort = 0
    if (sample) {
        const liveSince = dayjs(sample.version_live_since)
        const judgeableFrom = liveSince.add(MIN_VERSION_AGE_HOURS, 'hour')
        const ageDone = !judgeableFrom.isAfter(now)
        readyAt = ageDone ? null : judgeableFrom
        steps.push({
            key: 'age',
            title: 'Live for 2 days',
            state: ageDone ? 'done' : 'waiting',
            detail: ageDone
                ? `This version went live ${liveSince.from(now)}.`
                : `This version went live ${liveSince.from(now)}. It can be judged from ${formatMoment(judgeableFrom, now, 'at')}.`,
            percent: ageDone
                ? null
                : Math.round((Math.max(0, now.diff(liveSince, 'hour')) / MIN_VERSION_AGE_HOURS) * 100),
        })

        sendsShort = Math.max(0, sample.required_sends - sample.tracked_sends)
        steps.push({
            key: 'sends',
            title: `${sample.required_sends} ${trackedEmails(sample.required_sends)} in 7 days`,
            state: sendsShort === 0 ? 'done' : 'waiting',
            detail:
                sendsShort === 0
                    ? `The busiest email step sent ${sample.tracked_sends} ${trackedEmails(sample.tracked_sends)} in the last 7 days.`
                    : `${sample.tracked_sends} of ${sample.required_sends} sent from the busiest email step in the last 7 days.`,
            percent: sendsShort === 0 ? null : Math.round((sample.tracked_sends / sample.required_sends) * 100),
        })
    }

    const lastChecked = schedule?.last_checked_at ? dayjs(schedule.last_checked_at) : null
    const nextCheck = schedule?.next_check_at ? dayjs(schedule.next_check_at) : null
    // A due time in the past means the scout is queued, so a check is imminent unless it is long overdue.
    const nextCheckText = !nextCheck
        ? null
        : nextCheck.isAfter(now)
          ? formatMoment(nextCheck, now, 'around')
          : now.diff(nextCheck, 'hour') < OVERDUE_GRACE_HOURS
            ? 'soon'
            : null
    // Without a sample, the metrics read failed or there is no email step, so readiness is unknown.
    const ready = enabled && !!sample && readyAt === null && sendsShort === 0
    steps.push({
        key: 'check',
        title: 'Scheduled check',
        state: !enabled ? 'blocked' : ready ? 'done' : 'waiting',
        detail: !enabled
            ? 'PostHog starts checking this workflow after you turn suggestions on.'
            : ready
              ? 'PostHog checks this workflow on a schedule and files a suggestion when it finds a change worth making.'
              : [
                    sample ? 'Suggestions can start once the steps above are done.' : null,
                    lastChecked
                        ? `Last checked ${lastChecked.from(now)}${sample ? ', not enough data yet' : ''}.`
                        : null,
                ]
                    .filter(Boolean)
                    .join(' '),
        percent: null,
    })

    let headline: string
    let detail: string | null = null
    if (!enabled) {
        headline = 'Turn on suggestions to start'
        detail = sample?.reached
            ? 'This workflow has enough data, so the first check runs within a day of turning them on.'
            : sample
              ? 'You can turn them on now. PostHog starts suggesting once the steps below are done.'
              : null
    } else if (sample && !ready) {
        headline =
            sendsShort > 0
                ? `Needs ${sendsShort} more ${trackedEmails(sendsShort)}`
                : `Can be judged from ${formatMoment(readyAt ?? now, now, 'at')}`
        detail =
            sendsShort > 0 && readyAt
                ? `Suggestions can start after that, and no earlier than ${formatMoment(readyAt, now, 'around')}.`
                : 'Suggestions can start at the first check after that.'
    } else {
        headline = nextCheckText
            ? `Next check ${nextCheckText}`
            : lastChecked
              ? 'Waiting for the next check'
              : 'First check within a day'
        detail = lastChecked ? `Last checked ${lastChecked.from(now)}.` : null
    }

    return { headline, detail, steps }
}
