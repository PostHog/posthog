import { ApiError, NetworkError } from 'lib/api'

/** Waits between retries of a load that failed for a reason that may clear on its own. */
export const TRANSIENT_LOAD_RETRY_DELAYS_MS = [1000, 3000]

/** A 404 from the tasks API — surfaced as a `NotFound` scene, not a generic error banner. */
export function isApiNotFound(errorObject: unknown): boolean {
    return errorObject instanceof ApiError && errorObject.status === 404
}

/** A 404 for a task this user could read before it was deleted. */
export function isTaskDeleted(errorObject: unknown): boolean {
    return isApiNotFound(errorObject) && (errorObject as ApiError).code === 'task_deleted'
}

/** A dropped connection, a rate limit, or a server error. A 4xx other than 429 fails the same way every time. */
export function isTransientLoadError(errorObject: unknown): boolean {
    if (!(errorObject instanceof ApiError)) {
        return false
    }
    return errorObject.status === undefined || errorObject.status === 429 || errorObject.status >= 500
}

/** Runs `load`, and runs it again after each delay while it fails with a transient error. Pass a kea
 * `breakpoint` as `wait` so a newer load cancels the pending retries. */
export async function retryTransientLoad<T>(load: () => Promise<T>, wait: (ms: number) => Promise<void>): Promise<T> {
    for (const delayMs of TRANSIENT_LOAD_RETRY_DELAYS_MS) {
        try {
            return await load()
        } catch (errorObject) {
            if (!isTransientLoadError(errorObject)) {
                throw errorObject
            }
        }
        await wait(delayMs)
    }
    return await load()
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

/** Message for a load that still failed after its retries. A failure the server gave no reason for
 * gets plain copy instead of the raw status text. */
export function loadFailureMessage(errorObject: unknown): string {
    if (errorObject instanceof NetworkError) {
        return "We couldn't reach PostHog. Check your connection, then select Retry."
    }
    if (errorObject instanceof ApiError && isTransientLoadError(errorObject) && !errorObject.detail) {
        return 'Something went wrong on our side. Wait a moment, then select Retry.'
    }
    return loadErrorMessage('', errorObject)
}
