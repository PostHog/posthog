/**
 * PostHog analytics for MCP UI Apps.
 *
 * Uses posthog-js-lite for minimal footprint - we only need capture functionality.
 * Events are only captured if POSTHOG_UI_APPS_TOKEN is set at build time.
 */
import { PostHog } from 'posthog-js-lite'

// These are injected at build time by Vite
declare const __POSTHOG_UI_APPS_TOKEN__: string | undefined
declare const __POSTHOG_MCP_APPS_ANALYTICS_BASE_URL__: string | undefined

const POSTHOG_TOKEN = typeof __POSTHOG_UI_APPS_TOKEN__ !== 'undefined' ? __POSTHOG_UI_APPS_TOKEN__ : undefined
const POSTHOG_HOST =
    typeof __POSTHOG_MCP_APPS_ANALYTICS_BASE_URL__ !== 'undefined'
        ? __POSTHOG_MCP_APPS_ANALYTICS_BASE_URL__
        : 'https://us.posthog.com'

let client: PostHog | null = null
let currentDistinctId: string | null = null

const log = (...args: any[]): void => {
    console.debug('[PostHog Analytics]', ...args)
}

/**
 * Initialize PostHog for UI Apps tracking.
 * Only initializes if POSTHOG_UI_APPS_TOKEN is set.
 */
export function initPostHog(appName: string, appVersion: string): void {
    if (client) {
        return
    }

    if (!POSTHOG_TOKEN) {
        return
    }

    log('Initializing PostHog client', { token: POSTHOG_TOKEN, host: POSTHOG_HOST, appName, appVersion })
    client = new PostHog(POSTHOG_TOKEN, { host: POSTHOG_HOST })
    client.register({
        $mcp_app_name: appName,
        $mcp_app_version: appVersion,
        // Stamped once per loaded app document. Host notifications currently arrive at
        // twice the connection count, and this separates a host that delivers each
        // notification twice from a host that mounts the app twice.
        $mcp_app_instance_id: newInstanceId(),
    })
}

function newInstanceId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID()
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

/**
 * Identify the user with their PostHog distinct ID from the MCP server.
 */
export function identifyUser(distinctId: string, toolName?: string): void {
    if (!client) {
        log('PostHog client not initialized while attempting to identify user', { distinctId, toolName })
        return
    }

    if (currentDistinctId === distinctId) {
        log('User already identified', { distinctId })
        return
    }

    log('Identifying user', { distinctId, toolName })
    client.identify(distinctId)
    currentDistinctId = distinctId

    if (toolName) {
        client.register({ $mcp_tool_name: toolName })
    }
}

/**
 * Capture a custom event.
 */
export function capture(eventName: string, properties?: { [key: string]: any }): void {
    if (client === null) {
        return
    }

    client.capture(eventName, properties)
}

/**
 * Capture app connection event.
 */
export function captureAppConnected(hostContext?: {
    hasStyles?: boolean | undefined
    hasFonts?: boolean | undefined
    availableDisplayModes?: string[] | undefined
}): void {
    capture('mcp_ui_app_connected', {
        has_host_styles: hostContext?.hasStyles,
        has_host_fonts: hostContext?.hasFonts,
        available_display_modes: hostContext?.availableDisplayModes,
    })
}

/**
 * Capture app connection error.
 */
export function captureAppConnectionError(error: Error): void {
    capture('mcp_ui_app_connection_error', {
        error_message: error.message,
        error_name: error.name,
    })
}

/**
 * Capture tool input received.
 */
export function captureToolInput(params: { toolName?: string | undefined; hasArguments?: boolean | undefined }): void {
    capture('mcp_ui_app_tool_input', {
        tool_name: params.toolName,
        has_arguments: params.hasArguments,
    })
}

/**
 * Capture tool result received.
 */
export function captureToolResult(params: {
    hasStructuredContent?: boolean | undefined
    hasAppData?: boolean | undefined
    contentLength?: number | undefined
    rendered?: boolean | undefined
}): void {
    capture('mcp_ui_app_tool_result', {
        has_structured_content: params.hasStructuredContent,
        has_app_data: params.hasAppData,
        content_length: params.contentLength,
        rendered: params.rendered,
    })
}

/**
 * Capture the app giving up on the host, which is the only signal that a person saw
 * a failed render instead of a chart.
 */
export function captureWaitTimeout(params: { phase: string; timeoutMs: number }): void {
    capture('mcp_ui_app_wait_timeout', {
        phase: params.phase,
        timeout_ms: params.timeoutMs,
    })
}

/**
 * Capture tool cancelled.
 */
export function captureToolCancelled(params: { toolName?: string | undefined; reason?: string | undefined }): void {
    capture('mcp_ui_app_tool_cancelled', {
        tool_name: params.toolName,
        reason: params.reason,
    })
}

/**
 * Capture host context changed.
 */
export function captureHostContextChanged(params: {
    hasStyles?: boolean | undefined
    hasFonts?: boolean | undefined
    theme?: string | undefined
}): void {
    capture('mcp_ui_app_host_context_changed', {
        has_styles: params.hasStyles,
        has_fonts: params.hasFonts,
        theme: params.theme,
    })
}

/**
 * Capture link opened via host.
 */
export function captureLinkOpened(url: string): void {
    capture('mcp_ui_app_link_opened', { url })
}
