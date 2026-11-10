import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import type { HealthIssue } from 'scenes/health/types'

/** The fields the `event_stopped` health check writes into an issue's payload. */
export interface StoppedEventPayload {
    event: string
    event_definition_id: string
    last_seen_at: string
    insight_count: number
    annotation?: { content: string; marked_at: string }
    daily_average_before?: number
    last_lib?: string
    last_path?: string
}

export function stoppedEventPayload(issue: HealthIssue): StoppedEventPayload {
    return issue.payload as StoppedEventPayload
}

export function stoppedEventStoppedAgo(payload: StoppedEventPayload, now: dayjs.Dayjs = dayjs()): string {
    const days = Math.max(1, now.diff(dayjs(payload.last_seen_at), 'day'))
    return `${pluralize(days, 'day')} ago`
}

export function stoppedEventDailyVolume(payload: StoppedEventPayload): string | null {
    return payload.daily_average_before ? `~${humanFriendlyLargeNumber(payload.daily_average_before)}` : null
}

/** Where the last events came from, to help find the code that stopped sending it. */
export function stoppedEventLastCapture(payload: StoppedEventPayload): string | null {
    return [payload.last_lib, payload.last_path].filter(Boolean).join(' · ') || null
}

export function stoppedEventAnnotationText(payload: StoppedEventPayload): string | null {
    if (!payload.annotation) {
        return null
    }
    return `Possibly related: "${payload.annotation.content}" on ${dayjs(payload.annotation.marked_at).format('MMM D')}`
}

export function stoppedEventPrompt(payload: StoppedEventPayload): string {
    const lines = [
        `The event "${payload.event}" stopped arriving in this project. It was last seen at ${payload.last_seen_at}, and ${pluralize(payload.insight_count, 'saved insight')} read it.`,
        ...(payload.daily_average_before
            ? [`In the week before it stopped, it arrived about ${payload.daily_average_before} times a day.`]
            : []),
        ...(payload.last_lib
            ? [
                  `The last events came from the ${payload.last_lib} SDK${payload.last_path ? ` on ${payload.last_path}` : ''}.`,
              ]
            : []),
        'Find out why it stopped. Check whether a similar event started arriving at the same time, which would mean it was renamed, and which insights still read the old name.',
    ]
    if (payload.annotation) {
        lines.push(
            `An annotation near that time says "${payload.annotation.content}" (${payload.annotation.marked_at}). Check whether that change is the cause.`
        )
    }
    lines.push(
        'Then tell me what to fix in my code, or which insights to update or delete if the event is gone for good.'
    )
    return lines.join(' ')
}
