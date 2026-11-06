export const AUTO_RESOLVE_MIN_DAYS = 1
export const AUTO_RESOLVE_MAX_DAYS = 365
export const AUTO_RESOLVE_DEFAULT_DAYS = 14

export function isValidAutoResolveDays(days: number | null | undefined): days is number {
    return (
        typeof days === 'number' &&
        Number.isInteger(days) &&
        days >= AUTO_RESOLVE_MIN_DAYS &&
        days <= AUTO_RESOLVE_MAX_DAYS
    )
}

// pinned: analytics event names - renaming breaks dashboards
export type AutoResolveChangeEvent =
    | 'error tracking auto resolve enabled'
    | 'error tracking auto resolve disabled'
    | 'error tracking auto resolve threshold changed'

export function autoResolveChangeEvent(
    previousDays: number | null,
    nextDays: number | null
): AutoResolveChangeEvent | null {
    if (previousDays === null && nextDays !== null) {
        return 'error tracking auto resolve enabled'
    }
    if (previousDays !== null && nextDays === null) {
        return 'error tracking auto resolve disabled'
    }
    if (previousDays !== null && nextDays !== null && previousDays !== nextDays) {
        return 'error tracking auto resolve threshold changed'
    }
    return null
}
