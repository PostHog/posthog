import type { App } from '@modelcontextprotocol/ext-apps'
import { useEffect, useRef, useState } from 'react'

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
    /** Stop polling after this many failed calls in a row. */
    maxConsecutiveErrors?: number
}

export interface UseToolPollingReturn<T> {
    data: T | null
    error: string | null
    /** Replace the data, for example with the response of an action the user started. */
    setData: (data: T) => void
}

function errorText(result: { content?: Array<{ type: string; text?: string }> }): string {
    return result.content?.find((c) => c.type === 'text')?.text ?? 'The status request failed.'
}

/**
 * Call a server tool again and again while the document is visible and `isDone` is false.
 * Polling pauses when the document is hidden and continues when it is visible again.
 */
export function useToolPolling<T>({
    app,
    initialData,
    toolName,
    getArguments,
    isDone,
    getIntervalSeconds,
    minIntervalSeconds = 3,
    maxConsecutiveErrors = 5,
}: UseToolPollingOptions<T>): UseToolPollingReturn<T> {
    const [data, setData] = useState<T | null>(initialData)
    const [error, setError] = useState<string | null>(null)
    const [failures, setFailures] = useState(0)
    const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden)
    const callbacks = useRef({ getArguments, isDone, getIntervalSeconds })
    callbacks.current = { getArguments, isDone, getIntervalSeconds }

    useEffect(() => {
        if (initialData !== null) {
            setData(initialData)
        }
    }, [initialData])

    useEffect(() => {
        const onVisibilityChange = (): void => setVisible(!document.hidden)
        document.addEventListener('visibilitychange', onVisibilityChange)
        return () => document.removeEventListener('visibilitychange', onVisibilityChange)
    }, [])

    useEffect(() => {
        if (!app || data === null || !visible || failures >= maxConsecutiveErrors || callbacks.current.isDone(data)) {
            return
        }
        let cancelled = false
        const delaySeconds = Math.max(minIntervalSeconds, callbacks.current.getIntervalSeconds(data))
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
    }, [app, data, visible, failures, toolName, minIntervalSeconds, maxConsecutiveErrors])

    return { data, error, setData }
}
