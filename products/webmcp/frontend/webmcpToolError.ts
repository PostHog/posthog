import type { BeforeSendFn } from 'posthog-js'

// posthog-js reads the name, and minification would rename the class.
const WEBMCP_TOOL_ERROR_NAME = 'WebMCPToolError'

/** A PostHog command that failed, for example bad HogQL or a missing resource. The agent gets the message. */
export class WebMCPToolError extends Error {
    constructor(message: string) {
        super(message)
        this.name = WEBMCP_TOOL_ERROR_NAME
    }
}

/**
 * posthog-js `capture_webmcp` captures an exception for each failed tool call. A failed command is an agent
 * mistake, not an app error, and the `$mcp_tool_call` event already records it. Transport failures still pass.
 */
export const dropWebMCPToolErrors: BeforeSendFn = (event) => {
    if (
        event.event === '$exception' &&
        event.properties?.$exception_source === 'mcp.tool_call' &&
        event.properties.$mcp_interface === 'webmcp' &&
        event.properties.$exception_list?.[0]?.type === WEBMCP_TOOL_ERROR_NAME
    ) {
        return null
    }
    return event
}
