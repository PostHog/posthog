import { AnyPropertyFilter, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

/**
 * Whether a rule's filters contain at least one row with a real `key`, recursively.
 *
 * Mirrors the backend `has_filter_values` gate (products/error_tracking/backend/logic):
 * an empty row the user hasn't finished picking a property for is dropped on the server and the
 * request 400s. Save/Test key off this so we don't offer actions the API will silently reject.
 */
export function filtersContainValues(filters: UniversalFiltersGroup): boolean {
    return (filters.values ?? []).some((value: UniversalFiltersGroupValue) => {
        if (value && typeof value === 'object' && 'values' in value) {
            return filtersContainValues(value)
        }
        return Boolean((value as AnyPropertyFilter)?.key)
    })
}

/**
 * Human-readable message for a failed rule save, preferring the backend's DRF `detail`.
 *
 * kea-loaders dispatches `<key>Failure(error.message, error)`, so pass it the second arg
 * (the `ApiError` object) to reach `detail`; a bare string is accepted as a fallback.
 */
export function ruleSaveErrorMessage(error: unknown): string {
    if (error && typeof error === 'object') {
        const apiError = error as { detail?: string | null; message?: string }
        if (apiError.detail) {
            return apiError.detail
        }
        if (apiError.message) {
            return apiError.message
        }
    }
    if (typeof error === 'string' && error.length > 0) {
        return error
    }
    return 'Something went wrong saving this rule. Please try again.'
}
