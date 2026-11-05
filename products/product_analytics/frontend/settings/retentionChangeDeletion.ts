import { EventsPassSchedule, nextPassOn } from './nextPassOn'

export interface RetentionPeriods {
    retentionMonths: number | null
    defaultMonths: number
    monthlyDefaultMonths: number | null
    planMonths: number
    nextMonthlyCleanupOn: string
    passSchedule: EventsPassSchedule | null
}

export interface RetentionDeletion {
    monthly: boolean
    deletesOn: string | null
}

function deletesKeptEvents(periods: RetentionPeriods, months: number | null): boolean {
    const { retentionMonths, monthlyDefaultMonths } = periods
    if (retentionMonths === null) {
        return months !== null && (monthlyDefaultMonths === null || months < monthlyDefaultMonths)
    }
    if (months !== null) {
        return months < retentionMonths
    }
    if (monthlyDefaultMonths !== null) {
        return monthlyDefaultMonths < retentionMonths
    }
    return (
        (periods.passSchedule?.default_period_deletes ?? true) &&
        periods.defaultMonths < Math.min(periods.planMonths, retentionMonths)
    )
}

export function retentionChangeDeletion(periods: RetentionPeriods, months: number | null): RetentionDeletion | null {
    if (!deletesKeptEvents(periods, months)) {
        return null
    }
    if (months !== null || periods.monthlyDefaultMonths !== null) {
        return { monthly: true, deletesOn: periods.nextMonthlyCleanupOn }
    }
    return { monthly: false, deletesOn: periods.passSchedule && nextPassOn(periods.passSchedule) }
}
