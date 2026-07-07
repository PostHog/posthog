import { ApiError } from 'lib/api'

/** A 404 from the tasks API — surfaced as a `NotFound` scene, not a generic error banner. */
export function isApiNotFound(errorObject: unknown): boolean {
    return errorObject instanceof ApiError && errorObject.status === 404
}

/** Best-effort human message for a failed load: explicit `error` string first, then the
 * `ApiError` detail/statusText, then a plain `Error.message`, else a generic fallback. */
export function loadErrorMessage(error: string, errorObject: unknown): string {
    if (error) {
        return error
    }
    if (errorObject instanceof ApiError && (errorObject.detail || errorObject.statusText)) {
        return errorObject.detail || errorObject.statusText || 'Something went wrong.'
    }
    if (errorObject instanceof Error && errorObject.message) {
        return errorObject.message
    }
    return 'Something went wrong.'
}
