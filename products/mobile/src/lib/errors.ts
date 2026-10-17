import { ApiError } from '@/api/client'

export function toError(value: unknown): Error {
    return value instanceof Error ? value : new Error(String(value))
}

/** One line for a failed action: the server's own words when it sent some. */
export function actionErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        return error.detail ?? `PostHog couldn't do that (error ${error.status}). Try again.`
    }
    if (error instanceof TypeError) {
        return "Couldn't reach PostHog. Check your connection and try again."
    }
    return toError(error).message
}
