import type { CaptureError } from 'posthog-node'

import { posthogCaptureEventsLostTotal } from './metrics'

const UNDELIVERED = 'undelivered'

// The bundle can hold more than one copy of posthog-node, where `instanceof` fails, so the error is matched by shape.
function isCaptureError(error: unknown): error is CaptureError {
    if (!(error instanceof Error) || error.name !== 'CaptureError') {
        return false
    }
    const { drops, retryExhausted } = error as Partial<CaptureError>
    return Array.isArray(drops) && Array.isArray(retryExhausted)
}

/**
 * The events a failed capture batch lost, by reason. A dropped event counts under the drop detail
 * capture or the client gave it. An event with no accepted result counts as `undelivered`: its
 * request failed, its retries ran out, or it was still queued at shutdown.
 */
function countCaptureLosses(error: CaptureError): Map<string, number> {
    const losses = new Map<string, number>()
    const add = (reason: string, count: number): void => {
        if (count > 0) {
            losses.set(reason, (losses.get(reason) ?? 0) + count)
        }
    }
    for (const drop of error.drops) {
        // The detail becomes a metric label, so an unexpected value from the far end must not add series without bound.
        add(drop.details && /^[a-z0-9_ ]{1,64}$/.test(drop.details) ? drop.details : 'other', 1)
    }
    add(UNDELIVERED, error.retryExhausted.length)
    return losses
}

/** The client reports every event it loses only through `'error'`, including events capture drops inside a 200 response. */
export function recordCaptureLosses(client: { on(event: 'error', listener: (error: unknown) => void): unknown }): void {
    client.on('error', (error) => {
        if (!isCaptureError(error)) {
            return
        }
        for (const [reason, count] of countCaptureLosses(error)) {
            posthogCaptureEventsLostTotal.inc({ endpoint: error.endpoint, reason }, count)
        }
        console.warn('[MCP] PostHog client lost events:', error.message)
    })
}
