import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    JourneyApi,
    JourneyRunApi,
    JourneyRunDetailApi,
    JourneyRunStatusEnumApi,
    JourneyRunStepApi,
    JourneyRunTriggerEnumApi,
    JourneyStepFailureReasonEnumApi,
} from './generated/api.schemas'

export const RUNS_PAGE_SIZE = 10
// A run takes tens of seconds, so a few seconds between checks shows the result soon after it lands.
export const RUN_POLL_INTERVAL_MS = 3000

export const RUN_STATUS_LABELS: Record<JourneyRunStatusEnumApi, string> = {
    pending: 'Queued',
    running: 'Running',
    passed: 'Passed',
    failed: 'Failed',
    errored: "Didn't finish",
}

export const RUN_STATUS_TAG_TYPES: Record<JourneyRunStatusEnumApi, LemonTagType> = {
    pending: 'muted',
    running: 'primary',
    passed: 'success',
    failed: 'danger',
    errored: 'warning',
}

export const RUN_TRIGGER_LABELS: Record<JourneyRunTriggerEnumApi, string> = {
    manual: 'Manual',
    deploy: 'Deploy',
}

/** Short, sentence-case names for why a step failed. The step's own message carries the detail. */
export const FAILURE_REASON_LABELS: Record<JourneyStepFailureReasonEnumApi, string> = {
    element_not_found: 'Element not found',
    element_not_visible: 'Element not visible',
    element_obscured: 'Element covered by another element',
    element_outside_viewport_unreachable: "Element out of reach, the page can't scroll to it",
    navigation_mismatch: 'Ended up on a different page',
    navigation_failed: "Page didn't load",
    navigation_blocked: 'Page outside the authorized URLs',
    timeout: 'Ran out of time',
}

export function isRunActive(status: JourneyRunStatusEnumApi): boolean {
    return status === 'pending' || status === 'running'
}

export function failureReasonLabel(reason: JourneyStepFailureReasonEnumApi | null): string {
    return reason ? FAILURE_REASON_LABELS[reason] : 'Failed'
}

/** "Step 2: element not visible", with the step counted from 1 as the UI shows it. */
function lowerFirst(text: string): string {
    return `${text.charAt(0).toLowerCase()}${text.slice(1)}`
}

export function describeFailedStep(index: number, reason: JourneyStepFailureReasonEnumApi | null): string {
    return `Step ${index + 1}: ${lowerFirst(failureReasonLabel(reason))}`
}

/** Why a run can't open a URL, judged on its text, mirroring the server's shape check. Null when it can. */
export function runUrlError(value: string): string | null {
    let parsed: URL
    try {
        parsed = new URL(value)
    } catch {
        return 'Enter a full URL, starting with http:// or https://.'
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return 'Enter a URL that starts with http:// or https://.'
    }
    if (!parsed.hostname) {
        return 'Enter a URL that includes a host name.'
    }
    if (parsed.username || parsed.password) {
        return 'Remove the user name and password from the URL.'
    }
    return null
}

/**
 * The URL a run of the journey opens, before any origin override, or null when it has none. Mirrors
 * `recorded_start_url` in the backend: the start URL when set, else a first step that is an exact pageview of a full URL.
 */
export function journeyRunStartUrl(journey: Pick<JourneyApi, 'start_url' | 'steps'>): string | null {
    if (journey.start_url) {
        return journey.start_url
    }
    const first = journey.steps[0]
    if (first?.type === 'pageview' && (first.url_matching ?? 'exact') === 'exact' && !runUrlError(first.url)) {
        return first.url
    }
    return null
}

export function originOf(url: string): string | null {
    try {
        return new URL(url).origin
    } catch {
        return null
    }
}

/** The origin a run tested: the override when one was given, else the origin of the page it opened. */
export function runOrigin(run: Pick<JourneyRunApi, 'base_url' | 'start_url'>): string | null {
    return run.base_url ?? (run.start_url ? originOf(run.start_url) : null)
}

/** Seconds between the run starting and ending, or null while either is unknown. */
export function runDurationSeconds(run: Pick<JourneyRunApi, 'started_at' | 'finished_at'>): number | null {
    if (!run.started_at || !run.finished_at) {
        return null
    }
    return Math.max(0, dayjs(run.finished_at).diff(dayjs(run.started_at), 'millisecond') / 1000)
}

export function shortCommitSha(sha: string): string {
    return sha.slice(0, 7)
}

export function firstFailedStep(steps: JourneyRunStepApi[]): JourneyRunStepApi | null {
    return steps.find((step) => step.status === 'failed') ?? null
}

export function changedSteps(steps: JourneyRunStepApi[]): JourneyRunStepApi[] {
    return steps.filter((step) => step.visual_change === 'changed')
}

/** One line that says how the run went, for the run's header. */
export function runSummary(run: Pick<JourneyRunDetailApi, 'status' | 'steps'>): string {
    switch (run.status) {
        case 'pending':
            return 'Waiting for a browser'
        case 'running':
            return 'Running the steps'
        case 'errored':
            return "The run couldn't finish"
        case 'failed': {
            const failed = firstFailedStep(run.steps)
            if (!failed) {
                return 'Failed'
            }
            const reason = failed.failure_reason ? `: ${lowerFirst(FAILURE_REASON_LABELS[failed.failure_reason])}` : ''
            return `Failed at step ${failed.index + 1}${reason}`
        }
        case 'passed': {
            const changed = changedSteps(run.steps).length
            if (changed === 0) {
                return 'Passed'
            }
            return `Passed · ${changed} ${changed === 1 ? 'step looks' : 'steps look'} different`
        }
    }
}

/** The step a reader needs first: the failed step, else the first step that looks different. */
export function focusStepIndex(steps: JourneyRunStepApi[]): number | null {
    return (firstFailedStep(steps) ?? changedSteps(steps)[0] ?? null)?.index ?? null
}

/**
 * Steps whose screenshot opens without a click. A failed run opens only the failed step, so nothing above it grows
 * once its images load and the page stays on the failure. A passed run opens every step that looks different.
 */
export function defaultOpenStepIndexes(steps: JourneyRunStepApi[]): Set<number> {
    const failed = firstFailedStep(steps)
    return new Set(failed ? [failed.index] : changedSteps(steps).map((step) => step.index))
}
