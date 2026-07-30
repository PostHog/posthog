import type { ExecInnerCallProperties } from '@/tools/exec'

/**
 * `$mcp_tool_call` properties for the CLI. Value-free by design: raw error
 * messages and inputs can carry caller-supplied content and API response
 * bodies, which must never reach usage analytics. Mirrors the hosted server,
 * whose tool-call events carry only the error flag — plus a bounded
 * classification so failures stay diagnosable.
 */
export function buildToolCallProperties(
    toolName: string,
    properties: ExecInnerCallProperties
): Record<string, unknown> {
    return {
        tool_name: toolName,
        $mcp_tool_name: toolName,
        $mcp_duration_ms: properties.duration_ms,
        $mcp_is_error: !properties.success,
        output_format: properties.output_format,
        ...(properties.success ? {} : { error_class: errorClass(properties) }),
        ...(properties.error_status !== undefined ? { error_status: properties.error_status } : {}),
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
