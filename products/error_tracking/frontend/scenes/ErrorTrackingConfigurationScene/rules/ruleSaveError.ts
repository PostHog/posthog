import { ApiError } from 'lib/api-error'

/**
 * What the rule modal shows when a save is rejected. A rejected filter or regex explains itself
 * through `detail`; a 500 or a dropped connection carries no reason worth showing.
 */
export function ruleSaveErrorMessage(errorObject: unknown): string {
    if (errorObject instanceof ApiError && errorObject.detail) {
        return errorObject.detail
    }
    return 'Could not save the rule. Your changes are still here, so you can try again.'
}
