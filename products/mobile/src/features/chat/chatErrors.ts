import { ApiError, NotSignedInError } from '@/api/client'
import { isRecord } from '@/lib/records'

import type { ChatError } from './types'

const DESKTOP_ACCESS_REQUIRED = 'PostHog Desktop access is required to run tasks in the cloud.'
const DESKTOP_ACCESS_UNVERIFIED = "We couldn't verify PostHog Desktop access. Try again."
const DESKTOP_USAGE_LIMIT = "You've reached your PostHog Desktop usage limit."
const NOT_QUEUED = "Your message didn't reach the agent. Try again in a moment."
const REPORT_TASK_CAP = 'This report has reached its chat limit. Try again later.'

function retryHint(seconds: number | undefined): string {
    if (!seconds) {
        return 'Try again in a moment.'
    }
    if (seconds < 90) {
        return `Try again in ${seconds} seconds.`
    }
    return `Try again in ${Math.ceil(seconds / 60)} minutes.`
}

function isAbortError(error: unknown): boolean {
    return error instanceof Error && error.name === 'AbortError'
}

export function isNetworkError(error: unknown): boolean {
    if (error instanceof ApiError || error instanceof NotSignedInError || isAbortError(error)) {
        return false
    }
    // fetch reports a lost connection as a TypeError on every platform the app runs on.
    return error instanceof TypeError || (error instanceof Error && /network|connection|socket/i.test(error.message))
}

/** The tasks API's PostHog Desktop gate and limits. Their copy is under `error`, which `ApiError.detail` carries. */
function taskRunError(error: ApiError): ChatError | undefined {
    const type = isRecord(error.body) ? error.body.type : undefined
    if (error.status === 403 && error.code === 'code_access_required') {
        // The server copy names the reason, such as a Startup plan or prepaid credits.
        return { kind: 'access', message: error.detail ?? DESKTOP_ACCESS_REQUIRED }
    }
    if (error.status === 503 && error.code === 'desktop_access_unavailable') {
        return { kind: 'unavailable', message: DESKTOP_ACCESS_UNVERIFIED }
    }
    if (error.status === 429 && error.code === 'signal_report_task_cap') {
        // A one-report chat counts toward the report's discussion limit, on create and on `run/`.
        return { kind: 'throttled', message: error.detail ?? REPORT_TASK_CAP }
    }
    if (error.status === 429 && (error.code === 'usage_limit_exceeded' || type === 'billing_limit')) {
        return {
            kind: 'throttled',
            message: error.detail ?? DESKTOP_USAGE_LIMIT,
            retryAfterSeconds: error.retryAfterSeconds,
        }
    }
    if (error.status === 502 && error.detail?.startsWith('Failed to queue')) {
        return { kind: 'unavailable', message: NOT_QUEUED }
    }
    return undefined
}

export function toChatError(error: unknown): ChatError {
    if (error instanceof NotSignedInError) {
        return { kind: 'auth', message: 'Sign in again to keep chatting.' }
    }
    if (error instanceof ApiError) {
        const taskError = taskRunError(error)
        if (taskError) {
            return taskError
        }
        switch (error.status) {
            case 401:
                return { kind: 'auth', message: 'Sign in again to keep chatting.' }
            case 402:
                return {
                    kind: 'credits',
                    message:
                        'Your organization is out of AI credits. An admin can raise the limit in Billing settings.',
                }
            case 403:
                return {
                    kind: 'auth',
                    message: "Your sign-in can't use PostHog AI in this project. Sign out and sign in again.",
                }
            case 404:
                return { kind: 'not_found', message: 'This chat no longer exists. Start a new chat.' }
            case 409:
                return {
                    kind: 'busy',
                    message: 'PostHog AI is still answering your last message. Try again when it finishes.',
                }
            case 429:
                return {
                    kind: 'throttled',
                    // The throttle's `detail` is written for people, so it wins over generic copy.
                    message: error.detail ?? `You've sent a lot of messages. ${retryHint(error.retryAfterSeconds)}`,
                    retryAfterSeconds: error.retryAfterSeconds,
                }
            case 503:
                return {
                    kind: 'unavailable',
                    message: `PostHog AI is busy right now. ${retryHint(error.retryAfterSeconds)}`,
                    retryAfterSeconds: error.retryAfterSeconds,
                }
            case 400:
                return {
                    kind: 'invalid',
                    // Such as "Invalid resume_from_run_id" or a model the account cannot use.
                    message: error.detail ?? "PostHog AI couldn't take this message. Start a new chat and try again.",
                }
            default:
                if (error.status >= 500) {
                    return { kind: 'unavailable', message: 'PostHog AI ran into a problem. Try again.' }
                }
                return { kind: 'unknown', message: 'Something went wrong. Try again.' }
        }
    }
    if (isNetworkError(error)) {
        return { kind: 'network', message: "Couldn't reach PostHog. Check your connection and try again." }
    }
    return { kind: 'unknown', message: 'Something went wrong. Try again.' }
}
