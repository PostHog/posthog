import { dayjs } from 'lib/dayjs'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDuration } from 'lib/utils/durations'

import {
    ReviewRunApi,
    ReviewRunStatusEnumApi,
    ReviewRunTriggerEnumApi,
    ReviewRunVerdictEnumApi,
    StamphogReviewRunsListTrigger,
} from '../../generated/api.schemas'

/** How a run's outcome reads at a glance: the tag color plus the word on the tag. */
export type OutcomeDisplay = { type: LemonTagType; label: string }

const VERDICT_DISPLAY: Record<ReviewRunVerdictEnumApi, OutcomeDisplay> = {
    [ReviewRunVerdictEnumApi.Approved]: { type: 'success', label: 'Approved' },
    [ReviewRunVerdictEnumApi.Refused]: { type: 'danger', label: 'Refused' },
    [ReviewRunVerdictEnumApi.Escalate]: { type: 'warning', label: 'Escalated' },
    [ReviewRunVerdictEnumApi.Error]: { type: 'danger', label: 'Errored' },
    [ReviewRunVerdictEnumApi.Wait]: { type: 'default', label: 'Waiting' },
    [ReviewRunVerdictEnumApi.None]: { type: 'muted', label: 'No verdict' },
}

const STATUS_DISPLAY: Record<ReviewRunStatusEnumApi, OutcomeDisplay> = {
    [ReviewRunStatusEnumApi.Queued]: { type: 'default', label: 'Queued' },
    [ReviewRunStatusEnumApi.Reviewing]: { type: 'primary', label: 'Reviewing' },
    [ReviewRunStatusEnumApi.Gated]: { type: 'caution', label: 'Gated' },
    [ReviewRunStatusEnumApi.Completed]: { type: 'muted', label: 'Completed' },
    [ReviewRunStatusEnumApi.Failed]: { type: 'danger', label: 'Failed' },
    [ReviewRunStatusEnumApi.Superseded]: { type: 'muted', label: 'Superseded' },
}

const TRIGGER_LABEL: Record<ReviewRunTriggerEnumApi, string> = {
    [ReviewRunTriggerEnumApi.SelfDriving]: 'Self-driving',
    [ReviewRunTriggerEnumApi.Label]: 'Label',
    [ReviewRunTriggerEnumApi.All]: 'Every PR',
}

export function verdictDisplay(verdict: ReviewRunVerdictEnumApi): OutcomeDisplay {
    return VERDICT_DISPLAY[verdict] ?? { type: 'muted', label: verdict }
}

export function statusDisplay(status: ReviewRunStatusEnumApi): OutcomeDisplay {
    return STATUS_DISPLAY[status] ?? { type: 'muted', label: status }
}

export function triggerLabel(trigger: ReviewRunTriggerEnumApi): string {
    return TRIGGER_LABEL[trigger] ?? trigger
}

/**
 * Options for the trigger filter, derived from the labels the table already uses.
 *
 * The query-param enum and the response enum carry the same values, so one list keeps the filter
 * and the column from calling the same run different things.
 */
export const TRIGGER_OPTIONS: { value: StamphogReviewRunsListTrigger; label: string }[] = Object.entries(
    TRIGGER_LABEL
).map(([value, label]) => ({ value: value as StamphogReviewRunsListTrigger, label }))

// Statuses that mean the run is over. Mirrors TERMINAL_STATUSES in the backend's facade/enums.py.
const TERMINAL_STATUSES: ReadonlySet<ReviewRunStatusEnumApi> = new Set([
    ReviewRunStatusEnumApi.Completed,
    ReviewRunStatusEnumApi.Failed,
    ReviewRunStatusEnumApi.Superseded,
    ReviewRunStatusEnumApi.Gated,
])

/**
 * How long the run took, or how long it has been going.
 *
 * A run still in flight is measured against now — a run wedged in the sandbox is exactly what someone
 * opens this table to find, and a blank cell would hide it. The status column is what says which of
 * the two a given number is.
 *
 * Terminal runs fall back to updated_at, because the supersede paths set the status without stamping
 * completed_at. Measuring those against now would grow a finished run's duration forever.
 */
export function runDuration(run: ReviewRunApi): string {
    const end = run.completed_at
        ? dayjs(run.completed_at)
        : TERMINAL_STATUSES.has(run.status)
          ? dayjs(run.updated_at)
          : dayjs()
    const seconds = end.diff(dayjs(run.created_at), 'second')
    if (seconds < 0) {
        return ''
    }
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/** Short SHA, the length GitHub itself shows. */
export function shortSha(sha: string): string {
    return sha.slice(0, 7)
}
