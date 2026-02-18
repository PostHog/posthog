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
import {
    type App,
    McpUiHostContextChangedNotificationSchema,
    McpUiToolCancelledNotificationSchema,
    McpUiToolInputNotificationSchema,
    McpUiToolResultNotificationSchema,
    useApp,
    useHostStyleVariables,
} from '@modelcontextprotocol/ext-apps/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
    capture,
    captureAppConnected,
    captureAppConnectionError,
    captureHostContextChanged,
    captureLinkOpened,
    captureToolCancelled,
    captureToolInput,
    captureToolResult,
    identifyUser,
    initPostHog,
} from '../analytics/posthog'
import { extractAnalytics } from '../types'

export interface UseToolResultOptions {
    /** App name shown to the host */
    appName: string
    /** App version */
    appVersion?: string
}

export interface UseToolResultReturn<T> {
    /** The parsed tool result data, or null if not yet received */
    data: T | null
    /** Whether the app is connected to the host */
    isConnected: boolean
    /** Connection or parsing error, if any */
    error: Error | null
    /** The App instance for advanced usage (e.g., opening links) */
    app: App | null
    /** Callback to open a link via the host */
    openLink: (url: string) => void
    /** Capture a custom analytics event */
    capture: typeof capture
}

/**
 * Parse tool result content, preferring structuredContent over text parsing.
 */
function parseToolResultContent<T>(structuredContent: unknown): T | null {
    // Always use structuredContent, never attempt to use text content
    if (structuredContent !== undefined && structuredContent !== null) {
        return structuredContent as T
    }

    return null
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
}: UseToolResultOptions): UseToolResultReturn<T> {
    const [data, setData] = useState<T | null>(null)
    const [parseError, setParseError] = useState<Error | null>(null)
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
            appInstance.setNotificationHandler(McpUiToolInputNotificationSchema, (notification) => {
                // Extract toolName from params if available (may be in extended params)
                const params = notification.params as Record<string, unknown>
                captureToolInput({
                    toolName: typeof params.toolName === 'string' ? params.toolName : undefined,
                    hasArguments: !!params.arguments,
                })
            })

            // Do NOT register partial tool input handler (streaming)
            // This is too noisy, happens for each chunk of input we get from the server
            // appInstance.setNotificationHandler(McpUiToolInputPartialNotificationSchema, () => {})

            // Register tool cancelled handler
            appInstance.setNotificationHandler(McpUiToolCancelledNotificationSchema, (notification) => {
                const params = notification.params as Record<string, unknown>
                captureToolCancelled({
                    toolName: typeof params.toolName === 'string' ? params.toolName : undefined,
                    reason: typeof params.reason === 'string' ? params.reason : undefined,
                })
            })

            // Register host context changed handler
            appInstance.setNotificationHandler(McpUiHostContextChangedNotificationSchema, (notification) => {
                // Cast to access theme which may be in notification params directly
                const params = notification.params as typeof notification.params & { theme?: string }
                captureHostContextChanged({
                    hasStyles: !!notification.params.styles,
                    hasFonts: false, // fonts not available in current SDK schema
                    theme: params.theme,
                })
            })

            // Register tool result handler
            appInstance.setNotificationHandler(McpUiToolResultNotificationSchema, (notification) => {
                try {
                    const parsed = parseToolResultContent<T>(notification.params.structuredContent)

                    // Extract analytics metadata and identify the user
                    const analytics = extractAnalytics(parsed)
                    if (analytics) {
                        identifyUser(analytics.distinctId, analytics.toolName)
                    }

                    captureToolResult({
                        hasStructuredContent: !!notification.params.structuredContent,
                        contentLength: notification.params.content?.length,
                    })

                    if (parsed !== null) {
                        setData(parsed)
                        setParseError(null)
                    } else {
                        const err = new Error('Unable to parse tool result')
                        console.error('[PostHog MCP App UI] Parse error:', err)
                        setParseError(err)
                    }
                } catch (e) {
                    const err = e instanceof Error ? e : new Error(String(e))
                    console.error('[PostHog MCP App UI] Exception:', err)
                    setParseError(err)
                }
            })
        },
    })

    // Apply host styles
    useHostStyleVariables(app)

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

    // Combine connection and parse errors
    const error = connectionError || parseError

    return {
        data,
        isConnected,
        error,
        app,
        openLink,
        capture,
    }
}
