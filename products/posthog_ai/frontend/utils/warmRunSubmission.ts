import { ApiError } from 'lib/api-error'
import { uuid } from 'lib/utils/dom'

import type { DisposablesManager } from '~/kea-disposables'

async function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
    let abort = (): void => {}
    try {
        return await new Promise((resolve, reject) => {
            abort = (): void => reject(signal.reason)
            signal.addEventListener('abort', abort, { once: true })
            if (signal.aborted) {
                abort()
            }
            promise.then(resolve, reject)
        })
    } finally {
        signal.removeEventListener('abort', abort)
    }
}

export async function submitWithWarmRunRetry<T>(
    send: (options: RequestInit) => Promise<T>,
    disposables: DisposablesManager
): Promise<T> {
    if (disposables.isDisposed) {
        throw new DOMException('Submission cancelled', 'AbortError')
    }
    const controller = new AbortController()
    const key = `warm-submission:${uuid()}`
    const deadlineKey = `${key}:deadline`
    const delayKey = `${key}:delay`
    const deadline = performance.now() + 20_000
    let retryToken: string | undefined
    let retryError: ApiError | undefined
    let delay = 250
    disposables.add(() => () => controller.abort(), key, { pauseOnPageHidden: false })
    try {
        while (true) {
            if (controller.signal.aborted) {
                throw controller.signal.reason
            }
            if (retryError && performance.now() >= deadline) {
                throw retryError
            }
            try {
                const result = await abortable(
                    send({
                        signal: controller.signal,
                        ...(retryToken ? { headers: { 'X-PostHog-Warm-Retry': retryToken } } : {}),
                    }),
                    controller.signal
                )
                if (controller.signal.aborted) {
                    throw controller.signal.reason
                }
                if (retryError && performance.now() >= deadline) {
                    throw retryError
                }
                return result
            } catch (error) {
                const token = error instanceof ApiError ? error.data?.retry_token : undefined
                if (
                    controller.signal.aborted ||
                    !(error instanceof ApiError) ||
                    error.status !== 503 ||
                    error.code !== 'warm_run_activation_unavailable' ||
                    typeof token !== 'string' ||
                    !token.trim()
                ) {
                    throw error
                }
                const remaining = deadline - performance.now()
                if (remaining <= 0) {
                    throw error
                }
                retryError = error
                if (!retryToken) {
                    // Only the server can confirm nondelivery and pin a create retry to the original run.
                    retryToken = token
                    disposables.add(
                        () => {
                            const timer = setTimeout(() => controller.abort(retryError), remaining)
                            return () => clearTimeout(timer)
                        },
                        deadlineKey,
                        { pauseOnPageHidden: false }
                    )
                }
            }
            try {
                await abortable(
                    new Promise<void>((resolve) => {
                        disposables.add(
                            () => {
                                const timer = setTimeout(resolve, Math.min(delay, deadline - performance.now()))
                                return () => clearTimeout(timer)
                            },
                            delayKey,
                            { pauseOnPageHidden: false }
                        )
                    }),
                    controller.signal
                )
            } finally {
                disposables.dispose(delayKey)
            }
            delay = Math.min(delay * 2, 1000)
        }
    } finally {
        disposables.dispose(deadlineKey)
        disposables.dispose(delayKey)
        disposables.dispose(key)
    }
}
