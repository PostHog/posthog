import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

const CANVAS_CHANNEL = 'posthog-canvas'
export const NOTEBOOK_FRAME_KEY_PREFIX = '__posthog_notebook_frame__:'
const MAX_CONCURRENT_REQUESTS = 8
const MAX_TOTAL_REQUESTS = 200
const MAX_TOTAL_MESSAGES = MAX_TOTAL_REQUESTS + 16
const MAX_TOTAL_RESPONSE_BYTES = 32 * 1024 * 1024
const MAX_REQUEST_KEY_LENGTH = 8 * 1024
const MAX_MESSAGE_ID_LENGTH = 128
const MAX_FRAME_PAGE_ROWS = 500
const REQUEST_TIMEOUT_MS = 30_000

type ArtifactMessage = {
    channel?: unknown
    type?: unknown
    id?: unknown
    method?: unknown
    payload?: unknown
    message?: unknown
}

export async function readWidgetFrame(
    allowedFrames: string[],
    loadFrame: (name: string, offset: number, limit: number, signal: AbortSignal) => Promise<WidgetFrameApi>,
    payload: unknown,
    signal: AbortSignal
): Promise<WidgetFrameApi> {
    const key =
        typeof payload === 'object' && payload !== null && typeof (payload as { key?: unknown }).key === 'string'
            ? (payload as { key: string }).key
            : ''
    const encodedRequest = key.startsWith(NOTEBOOK_FRAME_KEY_PREFIX) ? key.slice(NOTEBOOK_FRAME_KEY_PREFIX.length) : ''
    const [encodedName = '', rawOffset = '0', rawLimit = '100'] = encodedRequest.split(':')
    const name = decodeURIComponent(encodedName)
    const offset = Number(rawOffset)
    const limit = Number(rawLimit)
    if (!name || !allowedFrames.includes(name)) {
        throw new Error('This dataframe is not available to the widget')
    }
    if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1) {
        throw new Error('The dataframe page is invalid')
    }
    return await loadFrame(name, offset, Math.min(limit, MAX_FRAME_PAGE_ROWS), signal)
}

export type WidgetHostCallbacks = {
    onDataRequest: (method: string, payload: unknown, signal: AbortSignal) => Promise<unknown> | unknown
    onError?: (message?: string) => void
    onRendered?: () => void
}

export type WidgetHostMessageRouter = {
    route: (message: unknown) => Promise<void>
    dispose: () => void
}

export function createWidgetHostMessageRouter(
    post: (message: Record<string, unknown>) => void,
    callbacks: () => WidgetHostCallbacks,
    onExhausted?: () => void
): WidgetHostMessageRouter {
    let activeRequests = 0
    let totalRequests = 0
    let totalMessages = 0
    let totalResponseBytes = 0
    let disposed = false
    const activeControllers = new Set<AbortController>()
    const activeCancellations = new Set<() => void>()
    const activeTimeouts = new Set<ReturnType<typeof setTimeout>>()

    const dispose = (): void => {
        if (disposed) {
            return
        }
        disposed = true
        for (const controller of activeControllers) {
            controller.abort()
        }
        activeControllers.clear()
        for (const cancel of activeCancellations) {
            cancel()
        }
        activeCancellations.clear()
        for (const timeoutId of activeTimeouts) {
            clearTimeout(timeoutId)
        }
        activeTimeouts.clear()
    }

    const exhaust = (): void => {
        if (disposed) {
            return
        }
        dispose()
        onExhausted?.()
    }

    const route = async (raw: unknown): Promise<void> => {
        if (disposed) {
            return
        }
        totalMessages += 1
        if (totalMessages > MAX_TOTAL_MESSAGES) {
            exhaust()
            return
        }
        if (typeof raw !== 'object' || raw === null) {
            return
        }
        const message = raw as ArtifactMessage
        if (message.channel !== CANVAS_CHANNEL) {
            return
        }
        if (message.type === 'error') {
            callbacks().onError?.(typeof message.message === 'string' ? message.message.slice(0, 500) : undefined)
            return
        }
        if (message.type === 'rendered') {
            callbacks().onRendered?.()
            return
        }
        if (message.type === 'data-request') {
            totalRequests += 1
            if (totalRequests > MAX_TOTAL_REQUESTS) {
                exhaust()
                return
            }
        }
        if (
            message.type !== 'data-request' ||
            typeof message.id !== 'string' ||
            message.id.length > MAX_MESSAGE_ID_LENGTH ||
            typeof message.method !== 'string'
        ) {
            return
        }
        if (message.method !== 'stateGet') {
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: 'This Canvas method is not available in notebook widgets',
            })
            return
        }

        const requestKey =
            typeof message.payload === 'object' &&
            message.payload !== null &&
            typeof (message.payload as { key?: unknown }).key === 'string'
                ? (message.payload as { key: string }).key
                : null
        if (
            activeRequests >= MAX_CONCURRENT_REQUESTS ||
            requestKey === null ||
            requestKey.length > MAX_REQUEST_KEY_LENGTH
        ) {
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: 'Widget data request exceeds runtime limits',
            })
            return
        }

        activeRequests += 1
        const controller = new AbortController()
        activeControllers.add(controller)
        let cancelRequest = (): void => undefined
        const cancellation = new Promise<never>((_, reject) => {
            cancelRequest = () => reject(new Error('Widget data request canceled'))
        })
        activeCancellations.add(cancelRequest)
        let timeoutId: ReturnType<typeof setTimeout> | undefined
        const request = Promise.resolve().then(() =>
            callbacks().onDataRequest('stateGet', message.payload, controller.signal)
        )
        try {
            const result = await Promise.race([
                request,
                cancellation,
                new Promise<never>((_, reject) => {
                    const timer = setTimeout(() => {
                        activeTimeouts.delete(timer)
                        controller.abort()
                        reject(new Error('Widget data request timed out'))
                    }, REQUEST_TIMEOUT_MS)
                    timeoutId = timer
                    activeTimeouts.add(timer)
                }),
            ])
            if (disposed) {
                return
            }
            const responseBytes = new TextEncoder().encode(JSON.stringify(result)).byteLength
            if (totalResponseBytes + responseBytes > MAX_TOTAL_RESPONSE_BYTES) {
                exhaust()
                return
            }
            totalResponseBytes += responseBytes
            post({ channel: CANVAS_CHANNEL, type: 'data-response', id: message.id, ok: true, result })
        } catch (error) {
            if (disposed) {
                return
            }
            post({
                channel: CANVAS_CHANNEL,
                type: 'data-response',
                id: message.id,
                ok: false,
                error: error instanceof Error ? error.message : 'Widget data request failed',
            })
        } finally {
            if (timeoutId !== undefined) {
                clearTimeout(timeoutId)
                activeTimeouts.delete(timeoutId)
            }
            activeControllers.delete(controller)
            activeCancellations.delete(cancelRequest)
            activeRequests -= 1
            void request.catch(() => undefined)
        }
    }

    return { route, dispose }
}
