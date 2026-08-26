import { ApiError } from 'lib/api'

/** A 404 from the tasks API — surfaced as a `NotFound` scene, not a generic error banner. */
export function isApiNotFound(errorObject: unknown): boolean {
    return errorObject instanceof ApiError && errorObject.status === 404
}

export function apiErrorReason(errorObject: unknown): string | null {
    if (!(errorObject instanceof ApiError)) {
        return null
    }
    const bodyError = errorObject.data?.error
    if (typeof bodyError === 'string' && bodyError) {
        return bodyError
    }
    return errorObject.detail || errorObject.statusText || null
}

/** Best-effort human message for a failed load: explicit `error` string first, then the
 * `ApiError` reason, then a plain `Error.message`, else a generic fallback. */
export function loadErrorMessage(error: string, errorObject: unknown): string {
    if (error) {
        return error
    }
    const reason = apiErrorReason(errorObject)
    if (reason) {
        return reason
    }
    if (errorObject instanceof Error && errorObject.message) {
        return errorObject.message
    }
    return 'Something went wrong.'
}
