import type { ExecInnerCallProperties } from '@/tools/exec'
import { getToolCategory, getToolDescription } from '@/tools/toolDefinitions'

/**
 * `$mcp_tool_call` properties for the CLI. Value-free by design: raw error
 * messages and inputs can carry caller-supplied content and API response
 * bodies, which must never reach usage analytics. Mirrors the hosted server,
 * whose tool-call events carry only the error flag — plus a bounded
 * classification so failures stay diagnosable. Category and clipped
 * description come from the tool catalog (never the caller), matching the
 * hosted server's stamps so per-tool analytics see one schema.
 */
export function buildToolCallProperties(
    toolName: string,
    properties: ExecInnerCallProperties
): Record<string, unknown> {
    const category = getToolCategory(toolName)
    const description = getToolDescription(toolName)
    return {
        tool_name: toolName,
        $mcp_tool_name: toolName,
        $mcp_duration_ms: properties.duration_ms,
        $mcp_is_error: !properties.success,
        output_format: properties.output_format,
        ...(category ? { $mcp_tool_category: category } : {}),
        ...(description ? { $mcp_tool_description: description } : {}),
        ...(properties.success ? {} : { error_class: errorClass(properties), $mcp_error_type: errorType(properties) }),
        ...(properties.error_status !== undefined
            ? { error_status: properties.error_status, $mcp_error_status: properties.error_status }
            : {}),
    }
}

function errorClass(properties: ExecInnerCallProperties): 'validation_error' | 'api_error' | 'error' {
    if (properties.validation_error) {
        return 'validation_error'
    }
    if (properties.error_status !== undefined) {
        return 'api_error'
    }
    return 'error'
}

/**
 * The hosted server's `$mcp_error_type` vocabulary, derived from the little the
 * CLI records (a validation flag and an HTTP status) — without it, CLI failures
 * land in the analytics tools' untyped bucket and can't be broken down by reason.
 */
function errorType(
    properties: ExecInnerCallProperties
): 'validation' | 'permission' | 'rate_limited' | 'api_4xx' | 'api_5xx' | 'internal' {
    if (properties.validation_error) {
        return 'validation'
    }
    const status = properties.error_status
    if (status === undefined) {
        return 'internal'
    }
    if (status === 401 || status === 403) {
        return 'permission'
    }
    if (status === 429) {
        return 'rate_limited'
    }
    return status >= 500 ? 'api_5xx' : 'api_4xx'
}
