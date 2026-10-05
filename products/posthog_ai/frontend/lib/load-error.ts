import { ApiError, NetworkError, isBrowserNetworkFailure } from 'lib/api-error'

/** Shown instead of the browser's "Failed to fetch" wording, which tells the user nothing they can act on. */
export const NETWORK_LOAD_ERROR_MESSAGE = "Can't reach PostHog. Check your connection and try again."

/** A 404 from the tasks API — surfaced as a `NotFound` scene, not a generic error banner. */
export function isApiNotFound(errorObject: unknown): boolean {
    return errorObject instanceof ApiError && errorObject.status === 404
}

export function isNetworkLoadError(errorObject: unknown): boolean {
    return errorObject instanceof NetworkError || isBrowserNetworkFailure(errorObject)
}

/** Best-effort human message for a failed load: explicit `error` string first, then a connection
 * message for network failures, then the `ApiError` detail/statusText, then a plain `Error.message`,
 * else a generic fallback. */
export function loadErrorMessage(error: string, errorObject: unknown): string {
    if (error) {
        return error
    }
    if (isNetworkLoadError(errorObject)) {
        return NETWORK_LOAD_ERROR_MESSAGE
    }
    if (errorObject instanceof ApiError && (errorObject.detail || errorObject.statusText)) {
        return errorObject.detail || errorObject.statusText || 'Something went wrong.'
    }
    if (errorObject instanceof Error && errorObject.message) {
        return errorObject.message
    }
    return 'Something went wrong.'
}
