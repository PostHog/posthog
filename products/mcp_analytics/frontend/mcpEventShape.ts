import { PropertyFilterType } from '~/types'
import type { HogQLPropertyFilter } from '~/types'

// `mcp_tool_call` events arrive in three property shapes:
//   - native tools/call events (hono tools mode + SDK wrapping path): $mcp_tool_name
//   - SDK single-exec events: $mcp_tool_name = 'exec' with the real tool in
//     $mcp_exec_tool_call_name
//   - legacy hono exec inner-call events: only the snake_case tool_name key
// These fragments resolve every shape so queries neither drop exec-routed calls
// nor bucket them as "no value".
export const EFFECTIVE_TOOL_HOGQL =
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), nullIf(toString(properties.$mcp_tool_name), ''), nullIf(toString(properties.tool_name), ''))"

// Canonical $mcp_is_error where present, legacy `success` otherwise.
export const EFFECTIVE_IS_ERROR_HOGQL =
    'coalesce(toBool(properties.$mcp_is_error), not(toBool(properties.success)), false)'

// Canonical $mcp_duration_ms where present, legacy `duration_ms` otherwise.
export const EFFECTIVE_DURATION_HOGQL =
    'coalesce(toFloat(properties.$mcp_duration_ms), toFloat(properties.duration_ms))'

// In single-exec mode each invocation emits two events: the outer `exec`
// dispatcher wrapper and an inner event for the real tool. Excluding the wrapper
// counts each real call exactly once.
export const EXCLUDE_EXEC_WRAPPER_HOGQL = `${EFFECTIVE_TOOL_HOGQL} != 'exec'`

export const EXCLUDE_EXEC_WRAPPER_FILTER: HogQLPropertyFilter = {
    type: PropertyFilterType.HogQL,
    key: EXCLUDE_EXEC_WRAPPER_HOGQL,
}
