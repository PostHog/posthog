import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

export type EventsPassSchedule = Pick<
    EventsRetentionApi,
    'scheduled_pass_on' | 'first_pass_on' | 'default_window_deletes'
>

export interface EventsRetentionDraft {
    /** False while the default window applies, which the cleanup may not delete past yet. */
    isSet: boolean
    isShorter: boolean
}

/** The cleanup every 3 months that would first delete past the draft window, or null when none is known. */
export function nextPassOn(schedule: EventsPassSchedule, draft: EventsRetentionDraft): string | null {
    if (!draft.isSet && !schedule.default_window_deletes) {
        return null
    }
    if (schedule.scheduled_pass_on === null) {
        return draft.isSet ? schedule.first_pass_on : null
    }
    return draft.isShorter && schedule.first_pass_on > schedule.scheduled_pass_on
        ? schedule.first_pass_on
        : schedule.scheduled_pass_on
}
