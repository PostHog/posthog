/**
 * Shared hook for MCP UI Apps to handle tool results.
 *
 * This hook provides a simple way to:
 * - Connect to the MCP host
 * - Receive tool result notifications
 * - Apply host styling
 * - Handle errors and loading states
 * - Track analytics events via PostHog
 *
 * Usage:
 * ```tsx
 * function MyApp() {
 *     const { data, isConnected, error, app, capture } = useToolResult<MyDataType>({
 *         appName: 'My App',
 *         appVersion: '1.0.0',
 *     })
 *
 *     // Capture custom events
 *     const handleClick = () => {
 *         capture('button_clicked', { button_name: 'submit' })
 *     }
 *
 *     if (error) return <div>Error: {error.message}</div>
 *     if (!isConnected) return <div>Connecting...</div>
 *     if (!data) return <div>Waiting for data...</div>
 *
 *     return <MyVisualization data={data} />
 * }
 * ```
 */
import { type App, useApp, useHostStyles } from '@modelcontextprotocol/ext-apps/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    capture,
    captureAppConnected,
    captureAppConnectionError,
    captureHostContextChanged,
    captureLinkOpened,
    captureToolCancelled,
    captureToolInput,
    captureToolResult,
    captureWaitTimeout,
    identifyUser,
    initPostHog,
} from '../analytics/posthog'
import { APP_DATA_META_KEY, extractAnalytics } from '../types'

/**
 * How long the app waits for the host before it reports a failure instead of a
 * loading state. The host normally pushes the tool result within milliseconds of
 * the connection handshake, so this budget only expires when a notification never
 * arrives. A result that lands after the budget still clears the error and renders.
 */
export const DEFAULT_WAIT_TIMEOUT_MS = 20_000

export interface UseToolResultOptions {
    /** App name shown to the host */
    appName: string
    /** App version */
    appVersion?: string
    /**
     * How long to wait for the host to connect, and then for it to deliver a tool
     * result, before surfacing an error. Set to 0 to wait indefinitely.
     */
    waitTimeoutMs?: number
}

export interface ContainerDimensions {
    height?: number
    maxHeight?: number
    width?: number
    maxWidth?: number
}

export interface UseToolResultReturn<T> {
    /** The parsed tool result data, or null if not yet received */
    data: T | null
    /** Whether the app is connected to the host */
    isConnected: boolean
    /** Connection or parsing error, if any */
    error: Error | null
    /** Whether the tool call was cancelled by the user or host */
    isCancelled: boolean
    /** The App instance for advanced usage (e.g., opening links) */
    app: App | null
    /** Callback to open a link via the host */
    openLink: (url: string) => void
    /** Capture a custom analytics event */
    capture: typeof capture
    /** Container dimensions from the host, updated on context changes */
    containerDimensions: ContainerDimensions | null
    /** Re-read container dimensions from the host context */
    refreshContainerDimensions: () => void
}

/** What the app is waiting for, which decides whether a watchdog is armed. */
export type WaitPhase = 'connecting' | 'awaiting-result' | 'settled'

export interface WaitPhaseInput {
    isConnected: boolean
    hasData: boolean
    isCancelled: boolean
    /** A connection or parse failure the app can already report on its own. */
    hasError: boolean
}

/**
 * Decide what the app is still waiting for. `settled` covers every state the app
 * can already draw, including failures, so the watchdog never fires on top of an
 * error the app is showing.
 */
export function resolveWaitPhase({ isConnected, hasData, isCancelled, hasError }: WaitPhaseInput): WaitPhase {
    if (hasData || isCancelled || hasError) {
        return 'settled'
    }
    return isConnected ? 'awaiting-result' : 'connecting'
}

const WAIT_TIMEOUT_MESSAGES: Record<Exclude<WaitPhase, 'settled'>, string> = {
    connecting: "Couldn't load this app. Re-run the tool to try again.",
    'awaiting-result': "This app didn't get any results. Re-run the tool to try again.",
}

const PARSE_ERROR_MESSAGE = "Couldn't read the results for this app. Re-run the tool to try again."

/**
 * Parse tool result content, preferring structuredContent over the `_meta`
 * fallback. Never falls back to text content.
 */
export function parseToolResultContent<T>(structuredContent: unknown, meta?: unknown): T | null {
    // Prefer structuredContent when the host forwards it.
    if (structuredContent !== undefined && structuredContent !== null) {
        return structuredContent as T
    }

    // Coding-agent hosts suppress `structuredContent` so the model reads the
    // compact text table; the app's data then rides on `_meta` instead.
    const appData = (meta as Record<string, unknown> | undefined)?.[APP_DATA_META_KEY]
    if (appData !== undefined && appData !== null) {
        return appData as T
    }

    return null
}

function extractContainerDimensions(ctx: Record<string, unknown> | undefined | null): ContainerDimensions | null {
    const dims = ctx?.containerDimensions as Record<string, unknown> | undefined
    if (!dims) {
        return null
    }

    // Need this because TS doesn't want us to set keys with `undefined`
    const result: ContainerDimensions = {}
    if (typeof dims.height === 'number') {
        result.height = dims.height
    }
    if (typeof dims.maxHeight === 'number') {
        result.maxHeight = dims.maxHeight
    }
    if (typeof dims.width === 'number') {
        result.width = dims.width
    }
    if (typeof dims.maxWidth === 'number') {
        result.maxWidth = dims.maxWidth
    }
    return result
}

function log(...args: any[]): void {
    console.debug('[PostHog MCP App]', ...args)
}

/**
 * Hook for MCP UI Apps to receive and handle tool results.
 *
 * Handles all the boilerplate for connecting to the host, receiving tool results,
 * applying host styling, and tracking analytics.
 */
export function useToolResult<T = unknown>({
    appName,
    appVersion = '1.0.0',
    waitTimeoutMs = DEFAULT_WAIT_TIMEOUT_MS,
}: UseToolResultOptions): UseToolResultReturn<T> {
    const [data, setData] = useState<T | null>(null)
    const [parseError, setParseError] = useState<Error | null>(null)
    const [isCancelled, setIsCancelled] = useState(false)
    const [timedOutPhase, setTimedOutPhase] = useState<Exclude<WaitPhase, 'settled'> | null>(null)
    const [containerDimensions, setContainerDimensions] = useState<ContainerDimensions | null>(null)
    const hasLoggedConnection = useRef(false)

    // Initialize PostHog on first render
    useEffect(() => {
        log('Initializing PostHog', { appName, appVersion })
        initPostHog(appName, appVersion)
    }, [appName, appVersion])

    const {
        app,
        isConnected,
        error: connectionError,
    } = useApp({
        appInfo: { name: appName, version: appVersion },
        capabilities: {},
        onAppCreated: (appInstance) => {
            log('App created', { appInstance })

            // Register tool input handler
            appInstance.ontoolinput = (params) => {
                captureToolInput({
                    toolName: 'toolName' in params && params.toolName ? (params.toolName as string) : undefined, // toolName is not defined in the type
                    hasArguments: !!params.arguments,
                })
            }

            // Do NOT register partial tool input handler (streaming)
            // This is too noisy, happens for each chunk of input we get from the server
            // appInstance.ontoolinputpartial = () => {}

            // Register tool cancelled handler
            appInstance.ontoolcancelled = (params) => {
                setIsCancelled(true)
                captureToolCancelled({
                    toolName: 'toolName' in params && params.toolName ? (params.toolName as string) : undefined, // toolName is not defined in the type
                    reason: typeof params.reason === 'string' ? params.reason : undefined,
                })
            }

            // Register host context changed handler
            appInstance.onhostcontextchanged = (params) => {
                captureHostContextChanged({
                    hasStyles: !!params.styles,
                    hasFonts: !!params.styles?.css?.fonts,
                    theme: typeof params.theme === 'string' ? params.theme : undefined,
                })
                setContainerDimensions(extractContainerDimensions(params))
            }

            // Register tool result handler
            appInstance.ontoolresult = (params) => {
                try {
                    const meta = (params as { _meta?: Record<string, unknown> })._meta
                    const parsed = parseToolResultContent<T>(params.structuredContent, meta)

                    // Extract analytics metadata and identify the user
                    const analytics = extractAnalytics(parsed)
                    if (analytics) {
                        identifyUser(analytics.distinctId, analytics.toolName)
                    }

                    // `hasAppData` and `rendered` separate a healthy result that rode the
                    // `_meta` channel from one the app could not draw at all, which
                    // `hasStructuredContent` alone cannot tell apart.
                    captureToolResult({
                        hasStructuredContent: !!params.structuredContent,
                        hasAppData: meta?.[APP_DATA_META_KEY] !== undefined && meta[APP_DATA_META_KEY] !== null,
                        contentLength: params.content?.length,
                        rendered: parsed !== null,
                    })

                    if (parsed !== null) {
                        setData(parsed)
                        setParseError(null)
                    } else {
                        const err = new Error(PARSE_ERROR_MESSAGE)
                        console.error('[PostHog MCP App UI] Parse error:', err)
                        setParseError(err)
                    }
                } catch (e) {
                    const err = e instanceof Error ? e : new Error(String(e))
                    console.error('[PostHog MCP App UI] Exception:', err)
                    setParseError(err)
                }
            }
        },
    })

    // Apply host styles (CSS variables, theme, and fonts)
    useHostStyles(app, app?.getHostContext())

    // Track connection state and errors
    useEffect(() => {
        if (connectionError && !hasLoggedConnection.current) {
            console.error('[PostHog MCP App UI] Connection error:', connectionError)
            captureAppConnectionError(connectionError)
            hasLoggedConnection.current = true
        }
    }, [connectionError])

    useEffect(() => {
        if (isConnected && app && !hasLoggedConnection.current) {
            const hostContext = app.getHostContext()

            // Cast to access fonts which may not be in the current SDK type definitions
            const hostContextExtended = hostContext as typeof hostContext & { fonts?: unknown }
            captureAppConnected({
                hasStyles: !!hostContext?.styles,
                hasFonts: !!hostContextExtended?.fonts,
                availableDisplayModes: hostContext?.availableDisplayModes,
            })
            setContainerDimensions(extractContainerDimensions(hostContext as unknown as Record<string, unknown>))
            hasLoggedConnection.current = true
        }
    }, [isConnected, app])

    // Callback to open links via the host
    const openLink = useCallback(
        (url: string) => {
            captureLinkOpened(url)
            if (app) {
                app.openLink({ url })
            } else {
                window.open(url, '_blank', 'noopener,noreferrer')
            }
        },
        [app]
    )

    // Re-read container dimensions from the current host context
    const refreshContainerDimensions = useCallback(() => {
        if (!app) {
            return
        }
        const ctx = app.getHostContext()
        setContainerDimensions(extractContainerDimensions(ctx as unknown as Record<string, unknown>))
    }, [app])

    const waitPhase = resolveWaitPhase({
        isConnected,
        hasData: data !== null,
        isCancelled,
        hasError: connectionError !== null || parseError !== null,
    })

    // Without this watchdog a notification that never arrives leaves the app in its
    // loading state forever, which reads as a broken render rather than a failure the
    // person can retry.
    useEffect(() => {
        if (timedOutPhase !== null) {
            // A late connection or a late result moves the app out of the phase that
            // timed out, so drop the error and let the app draw what it now has.
            if (timedOutPhase !== waitPhase) {
                setTimedOutPhase(null)
            }
            return
        }
        if (waitPhase === 'settled' || waitTimeoutMs <= 0) {
            return
        }
        const timer = setTimeout(() => {
            log('Timed out waiting for the host', { waitPhase, waitTimeoutMs })
            setTimedOutPhase(waitPhase)
            captureWaitTimeout({ phase: waitPhase, timeoutMs: waitTimeoutMs })
        }, waitTimeoutMs)
        return () => clearTimeout(timer)
    }, [waitPhase, timedOutPhase, waitTimeoutMs])

    const timeoutError = useMemo(
        () => (timedOutPhase === null ? null : new Error(WAIT_TIMEOUT_MESSAGES[timedOutPhase])),
        [timedOutPhase]
    )

    // Combine connection, parse, and timeout errors
    const error = connectionError || parseError || timeoutError

    return {
        data,
        isConnected,
        error,
        isCancelled,
        app,
        openLink,
        capture,
        containerDimensions,
        refreshContainerDimensions,
    }
}
