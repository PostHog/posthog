import { ApiError } from 'lib/api-error'
import { uuid } from 'lib/utils/dom'

import type { DisposablesManager } from '~/kea-disposables'

function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
        const abort = (): void => reject(signal.reason)
        signal.addEventListener('abort', abort, { once: true })
        if (signal.aborted) {
            abort()
        }
        promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
    })
}

export async function submitWithWarmRunRetry<T>(
    send: (options: RequestInit) => Promise<T>,
    disposables: DisposablesManager
): Promise<T> {
    const controller = new AbortController()
    const key = `warm-submission:${uuid()}`
    disposables.add(() => () => controller.abort(), key, { pauseOnPageHidden: false })
    try {
        try {
            return await abortable(send({ signal: controller.signal }), controller.signal)
        } catch (error) {
            const token = error instanceof ApiError ? error.data?.retry_token : undefined
            if (
                controller.signal.aborted ||
                !(error instanceof ApiError) ||
                error.status !== 503 ||
                error.code !== 'warm_run_activation_unavailable' ||
                typeof token !== 'string' ||
                !token
            ) {
                throw error
            }
            // Only the server can confirm nondelivery and pin a create retry to the original run.
            const timer = setTimeout(() => controller.abort(error), 10_000)
            try {
                return await abortable(
                    send({ signal: controller.signal, headers: { 'X-PostHog-Warm-Retry': token } }),
                    controller.signal
                )
            } finally {
                clearTimeout(timer)
            }
        }
    } finally {
        disposables.dispose(key)
    }
}
