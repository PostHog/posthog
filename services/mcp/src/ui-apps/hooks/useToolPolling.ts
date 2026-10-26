import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useEffect, useRef, useState } from 'react'

import { parseToolResultContent } from './useToolResult'

export interface UseToolPollingOptions<T> {
    app: App | null
    /** Data the poll starts from, usually the tool result the host pushed. */
    initialData: T | null
    toolName: string
    /** Arguments for the next call, computed from the latest data. */
    getArguments: (data: T) => Record<string, unknown>
    /** Stop polling when this returns true. */
    isDone: (data: T) => boolean
    /** Seconds until the next call, computed from the latest data. */
    getIntervalSeconds: (data: T) => number
    minIntervalSeconds?: number
    /** After a failed call, the delay doubles up to this many seconds. */
    maxBackoffSeconds?: number
}

export interface UseToolPollingReturn<T> {
    data: T | null
    error: string | null
    /** Replace the data, for example with the response of an action the user started. */
    setData: (data: T) => void
    /** Call the tool now instead of waiting for the next attempt. */
    retry: () => void
}

function errorText(result: { content?: Array<{ type: string; text?: string }> }): string {
    return result.content?.find((c) => c.type === 'text')?.text ?? 'The status request failed.'
}

/**
 * Call a server tool again and again while the document is visible and `isDone` is false.
 * Polling pauses when the document is hidden and continues when it is visible again.
 * Failed calls do not stop polling. The delay doubles after each failure, up to `maxBackoffSeconds`.
 */
export function useToolPolling<T>({
    app,
    initialData,
    toolName,
    getArguments,
    isDone,
    getIntervalSeconds,
    minIntervalSeconds = 3,
    maxBackoffSeconds = 60,
}: UseToolPollingOptions<T>): UseToolPollingReturn<T> {
    const [data, setData] = useState<T | null>(initialData)
    const [error, setError] = useState<string | null>(null)
    const [failures, setFailures] = useState(0)
    const [retries, setRetries] = useState(0)
    const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden)
    const callbacks = useRef({ getArguments, isDone, getIntervalSeconds })
    callbacks.current = { getArguments, isDone, getIntervalSeconds }
    const retryNow = useRef(false)

    const retry = useCallback((): void => {
        retryNow.current = true
        setRetries((n) => n + 1)
    }, [])

    useEffect(() => {
        if (initialData !== null) {
            setData(initialData)
            setFailures(0)
            setError(null)
        }
    }, [initialData])

    useEffect(() => {
        const onVisibilityChange = (): void => {
            setVisible(!document.hidden)
            if (!document.hidden) {
                setFailures(0)
            }
        }
        document.addEventListener('visibilitychange', onVisibilityChange)
        return () => document.removeEventListener('visibilitychange', onVisibilityChange)
    }, [])

    useEffect(() => {
        if (!app || data === null || !visible || callbacks.current.isDone(data)) {
            return
        }
        let cancelled = false
        const intervalSeconds = Math.max(minIntervalSeconds, callbacks.current.getIntervalSeconds(data))
        const delaySeconds = retryNow.current
            ? 0
            : failures > 0
              ? Math.min(maxBackoffSeconds, intervalSeconds * 2 ** failures)
              : intervalSeconds
        retryNow.current = false
        const timer = setTimeout(async () => {
            try {
                const result = await app.callServerTool({
                    name: toolName,
                    arguments: callbacks.current.getArguments(data),
                })
                if (cancelled) {
                    return
                }
                const next = result.isError ? null : parseToolResultContent<T>(result.structuredContent, result._meta)
                if (next === null) {
                    setError(result.isError ? errorText(result) : 'The status response had no data.')
                    setFailures((n) => n + 1)
                    return
                }
                setError(null)
                setFailures(0)
                setData(next)
            } catch (e) {
                if (!cancelled) {
                    setError(e instanceof Error ? e.message : String(e))
                    setFailures((n) => n + 1)
                }
            }
        }, delaySeconds * 1000)
        return () => {
            cancelled = true
            clearTimeout(timer)
        }
    }, [app, data, visible, failures, retries, toolName, minIntervalSeconds, maxBackoffSeconds])

    return { data, error, setData, retry }
}
