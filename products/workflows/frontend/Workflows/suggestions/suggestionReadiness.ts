import { Dayjs, dayjs } from 'lib/dayjs'

import type { HogFlowOptimizationApi } from '../../generated/api.schemas'

export const MIN_VERSION_AGE_HOURS = 48

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

function formatMoment(moment: Dayjs, now: Dayjs): string {
    if (moment.isSame(now, 'day')) {
        return `today at ${moment.format('h:mm A')}`
    }
    if (moment.isSame(now.add(1, 'day'), 'day')) {
        return `tomorrow at ${moment.format('h:mm A')}`
    }
    return moment.format('ddd, MMM D [at] h:mm A')
}

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`
}

export function suggestionReadiness(
    optimization: HogFlowOptimizationApi | null,
    now: Dayjs = dayjs()
): SuggestionReadiness | null {
    if (!optimization) {
        return null
    }
    const { enabled, sample, schedule } = optimization
    const steps: ReadinessStep[] = [
        {
            key: 'enabled',
            title: 'Suggestions are on',
            state: enabled ? 'done' : 'blocked',
            detail: enabled ? 'PostHog may suggest changes to this workflow.' : 'Turn on "Suggest improvements".',
            percent: null,
        },
    ]

    let readyAt: Dayjs | null = null
    let sendsShort = 0
    if (sample) {
        const liveSince = dayjs(sample.version_live_since)
        readyAt = liveSince.add(MIN_VERSION_AGE_HOURS, 'hour')
        const ageDone = !readyAt.isAfter(now)
        const hoursLive = Math.max(0, now.diff(liveSince, 'hour'))
        steps.push({
            key: 'age',
            title: 'Live for 2 days',
            state: ageDone ? 'done' : 'waiting',
            detail: ageDone
                ? `This version went live ${liveSince.fromNow()}.`
                : `This version went live ${liveSince.fromNow()}. It can be judged from ${formatMoment(readyAt, now)}.`,
            percent: ageDone ? null : Math.round((hoursLive / MIN_VERSION_AGE_HOURS) * 100),
        })
        if (ageDone) {
            readyAt = null
        }

        sendsShort = Math.max(0, sample.required_sends - sample.tracked_sends)
        steps.push({
            key: 'sends',
            title: `${sample.required_sends} tracked sends in 7 days`,
            state: sendsShort === 0 ? 'done' : 'waiting',
            detail:
                sendsShort === 0
                    ? `The busiest email step had ${sample.tracked_sends} tracked sends in the last 7 days.`
                    : `${sample.tracked_sends} of ${sample.required_sends} on the busiest email step in the last 7 days. Only emails with open tracking count.`,
            percent: sendsShort === 0 ? null : Math.round((sample.tracked_sends / sample.required_sends) * 100),
        })
    }

    const lastChecked = schedule?.last_checked_at ? dayjs(schedule.last_checked_at) : null
    const nextCheck = schedule?.next_check_at ? dayjs(schedule.next_check_at) : null
    // A due time in the past means the scout is queued, so the check is imminent rather than missed.
    const nextCheckText = nextCheck
        ? nextCheck.isAfter(now)
            ? `around ${formatMoment(nextCheck, now)}`
            : 'soon'
        : null
    const ready = enabled && (!sample || sample.reached)
    const scheduleParts = [
        lastChecked ? `Last checked ${lastChecked.fromNow()}.` : null,
        nextCheckText ? `Next check ${nextCheckText}.` : 'First check within a day.',
    ].filter(Boolean)
    steps.push({
        key: 'check',
        title: 'Daily check',
        state: !enabled ? 'blocked' : ready ? 'done' : 'waiting',
        detail: !enabled
            ? 'PostHog reads this workflow once a day after you turn suggestions on.'
            : ready
              ? scheduleParts.join(' ')
              : [
                    'PostHog reads this workflow once a day and starts suggesting once the steps above are done.',
                    lastChecked ? `Last checked ${lastChecked.fromNow()}.` : null,
                ]
                    .filter(Boolean)
                    .join(' '),
        percent: null,
    })

    let headline: string
    let detail: string | null = null
    if (!enabled) {
        headline = 'Turn on suggestions to start'
        detail = !sample
            ? null
            : sample.reached
              ? 'This workflow has enough data, so the first check runs within a day of turning them on.'
              : 'You can turn them on now. PostHog starts suggesting once the steps below are done.'
    } else if (ready) {
        headline = nextCheckText ? `Next check ${nextCheckText}` : 'First check within a day'
        detail = lastChecked
            ? `Last checked ${lastChecked.fromNow()}. No change worth suggesting yet.`
            : 'This workflow has enough data to judge.'
    } else {
        headline =
            sendsShort > 0
                ? `Needs ${plural(sendsShort, 'more tracked send', 'more tracked sends')}`
                : `Can be judged from ${formatMoment(readyAt ?? now, now)}`
        detail =
            sendsShort > 0 && readyAt
                ? `The first daily check after that, and no earlier than ${formatMoment(readyAt, now)}, can suggest a change.`
                : 'The first daily check after that can suggest a change.'
    }

    return { headline, detail, steps }
}
