import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

export type EventsPassSchedule = Pick<
    EventsRetentionApi,
    'scheduled_pass_on' | 'first_pass_on' | 'default_period_deletes'
>

export function nextPassOn(schedule: EventsPassSchedule): string | null {
    if (!schedule.default_period_deletes || schedule.scheduled_pass_on === null) {
        return null
    }
    return schedule.first_pass_on > schedule.scheduled_pass_on ? schedule.first_pass_on : schedule.scheduled_pass_on
}
