import { ApiError, NotSignedInError } from '@/api/client'

import type { ChatError } from './types'

function retryHint(seconds: number | undefined): string {
    if (!seconds) {
        return 'Try again in a moment.'
    }
    if (seconds < 90) {
        return `Try again in ${seconds} seconds.`
    }
    return `Try again in ${Math.ceil(seconds / 60)} minutes.`
}

function errorAttr(body: unknown): string | undefined {
    if (typeof body !== 'object' || body === null) {
        return undefined
    }
    const attr = (body as Record<string, unknown>).attr
    return typeof attr === 'string' ? attr : undefined
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

export function toChatError(error: unknown): ChatError {
    if (error instanceof NotSignedInError) {
        return { kind: 'auth', message: 'Sign in again to keep chatting.' }
    }
    if (error instanceof ApiError) {
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
                return errorAttr(error.body) === 'content'
                    ? { kind: 'invalid', message: 'This message is too long. Shorten it and try again.' }
                    : {
                          kind: 'invalid',
                          message: "PostHog AI couldn't take this message. Start a new chat and try again.",
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
