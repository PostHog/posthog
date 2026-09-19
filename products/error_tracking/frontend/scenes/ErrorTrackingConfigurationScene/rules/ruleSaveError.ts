import { ApiError } from 'lib/api-error'

/**
 * Whether the response says the caller sent something the API refused, which is the only case
 * where `detail` describes the rule. A server-side failure carries a fixed placeholder instead:
 * the DRF exception handler answers 500 with detail "A server error occurred.", which tells the
 * user less than the fallback does and hides the part that matters, that the edit survives.
 */
function isClientError(status: number | undefined): boolean {
    return status !== undefined && status >= 400 && status < 500
}

/**
 * What the rule modal shows when a save is rejected. A rejected filter or regex explains itself
 * through `detail`; a 500 or a dropped connection carries no reason worth showing.
 */
export function ruleSaveErrorMessage(errorObject: unknown): string {
    if (errorObject instanceof ApiError && errorObject.detail && isClientError(errorObject.status)) {
        return errorObject.detail
    }
    return 'Could not save the rule. Your changes are still here, so you can try again.'
}
