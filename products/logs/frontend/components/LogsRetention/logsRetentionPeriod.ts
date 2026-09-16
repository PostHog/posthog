/**
 * Retention periods Logs accepts: the 14-day default or a whole number of 30-day months.
 * Mirrors `logs_retention_days_error` in `posthog/models/team/logs_retention.py`.
 */
export const LOGS_RETENTION_DEFAULT_DAYS = 14
export const LOGS_RETENTION_MONTH_DAYS = 30
export const LOGS_RETENTION_MAX_MONTHS = 120
/** Tiers available without the custom-retention flag. */
export const LOGS_RETENTION_BASE_TIERS_DAYS: number[] = [14, 30]
/** Tiers offered as buttons when the custom-retention flag is on; anything else is "Custom". */
export const LOGS_RETENTION_PRESET_DAYS: number[] = [14, 30, 90, 360]

export function isValidLogsRetentionDays(days: number, allowCustom: boolean): boolean {
    if (!Number.isInteger(days)) {
        return false
    }
    if (!allowCustom) {
        return LOGS_RETENTION_BASE_TIERS_DAYS.includes(days)
    }
    if (days === LOGS_RETENTION_DEFAULT_DAYS) {
        return true
    }
    return (
        days > 0 &&
        days <= LOGS_RETENTION_MONTH_DAYS * LOGS_RETENTION_MAX_MONTHS &&
        days % LOGS_RETENTION_MONTH_DAYS === 0
    )
}

export function isValidLogsRetentionMonths(months: number | undefined): months is number {
    return typeof months === 'number' && Number.isInteger(months) && months >= 1 && months <= LOGS_RETENTION_MAX_MONTHS
}

export function logsRetentionMonthsToDays(months: number): number {
    return months * LOGS_RETENTION_MONTH_DAYS
}

export function logsRetentionDaysToMonths(days: number): number | undefined {
    return days > 0 && days % LOGS_RETENTION_MONTH_DAYS === 0 ? days / LOGS_RETENTION_MONTH_DAYS : undefined
}

export function logsRetentionDaysLabel(days: number): string {
    if (days === 360) {
        return '1 year (360 days)'
    }
    const months = logsRetentionDaysToMonths(days)
    if (months !== undefined && months > 12) {
        return `${months} months (${days} days)`
    }
    return `${days} days`
}
