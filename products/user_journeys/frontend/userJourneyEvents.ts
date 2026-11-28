import posthog from 'posthog-js'

import type { ComparisonMode } from 'lib/components/VisualImageDiffViewer'

import type { JourneyRunDetailApi, JourneySourceEnumApi } from './generated/api.schemas'
import { changedSteps, firstFailedStep } from './journeyRuns'
import type { JourneyDraft } from './journeySteps'

// pinned: analytics event names, renaming them breaks the dashboards that read them
const FORM_OPENED_EVENT = 'user journey form opened'
const SAVED_EVENT = 'user journey saved'
const SAVE_FAILED_EVENT = 'user journey save failed'
const DELETED_EVENT = 'user journey deleted'
const VIEWED_EVENT = 'user journey viewed'
const RUN_STARTED_EVENT = 'user journey run started'
const RUN_START_FAILED_EVENT = 'user journey run start failed'
const RUN_VIEWED_EVENT = 'user journey run viewed'
const RUN_COMPARISON_MODE_CHANGED_EVENT = 'user journey run comparison mode changed'

export type JourneyFormMode = 'create' | 'edit'

function stepProperties(draft: JourneyDraft): Record<string, number> {
    return {
        step_count: draft.steps.length,
        pageview_step_count: draft.steps.filter((step) => step.type === 'pageview').length,
        element_click_step_count: draft.steps.filter((step) => step.type === 'element_click').length,
    }
}

export function captureJourneyFormOpened(
    mode: JourneyFormMode,
    prefilled: boolean,
    source: JourneySourceEnumApi
): void {
    posthog.capture(FORM_OPENED_EVENT, { mode, prefilled, source })
}

export function captureJourneySaved(mode: JourneyFormMode, draft: JourneyDraft): void {
    posthog.capture(SAVED_EVENT, {
        mode,
        source: draft.source,
        conversion_window_minutes: draft.conversion_window_minutes,
        has_start_url: draft.start_url.trim() !== '',
        ...stepProperties(draft),
    })
}

export function captureJourneySaveFailed(
    mode: JourneyFormMode,
    reason: 'invalid' | 'server',
    field: string | null
): void {
    posthog.capture(SAVE_FAILED_EVENT, { mode, reason, field })
}

export function captureJourneyDeleted(from: 'list' | 'detail'): void {
    posthog.capture(DELETED_EVENT, { from })
}

export function captureJourneyViewed(stepCount: number, source: JourneySourceEnumApi): void {
    posthog.capture(VIEWED_EVENT, { step_count: stepCount, source })
}

export function captureJourneyRunStarted(customOrigin: boolean): void {
    posthog.capture(RUN_STARTED_EVENT, { custom_origin: customOrigin })
}

export function captureJourneyRunStartFailed(reason: 'invalid' | 'in_progress' | 'server'): void {
    posthog.capture(RUN_START_FAILED_EVENT, { reason })
}

export function captureJourneyRunViewed(run: JourneyRunDetailApi): void {
    posthog.capture(RUN_VIEWED_EVENT, {
        status: run.status,
        trigger: run.trigger,
        step_count: run.steps.length,
        failed_step_index: firstFailedStep(run.steps)?.index ?? null,
        failure_reason: firstFailedStep(run.steps)?.failure_reason ?? null,
        changed_step_count: changedSteps(run.steps).length,
        has_baseline: run.baseline_run_id !== null,
    })
}

export function captureJourneyRunComparisonModeChanged(mode: ComparisonMode): void {
    posthog.capture(RUN_COMPARISON_MODE_CHANGED_EVENT, { mode })
}
