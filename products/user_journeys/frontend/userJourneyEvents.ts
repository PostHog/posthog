import posthog from 'posthog-js'

import type { JourneySourceEnumApi } from './generated/api.schemas'
import type { JourneyDraft } from './journeySteps'

// pinned: analytics event names, renaming them breaks the dashboards that read them
const FORM_OPENED_EVENT = 'user journey form opened'
const SAVED_EVENT = 'user journey saved'
const SAVE_FAILED_EVENT = 'user journey save failed'
const DELETED_EVENT = 'user journey deleted'
const VIEWED_EVENT = 'user journey viewed'

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
