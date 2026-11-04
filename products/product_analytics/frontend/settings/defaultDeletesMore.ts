import { EventsPassSchedule } from './nextPassOn'

export interface DefaultDeletionInput {
    retentionMonths: number | null
    defaultMonths: number
    monthlyDefaultMonths: number | null
    planMonths: number
    passSchedule: EventsPassSchedule | null
}

export function defaultDeletesMore({
    retentionMonths,
    defaultMonths,
    monthlyDefaultMonths,
    planMonths,
    passSchedule,
}: DefaultDeletionInput): boolean {
    if (retentionMonths === null) {
        return false
    }
    if (monthlyDefaultMonths !== null) {
        return monthlyDefaultMonths < retentionMonths
    }
    return (passSchedule?.default_period_deletes ?? true) && defaultMonths < Math.min(planMonths, retentionMonths)
}
