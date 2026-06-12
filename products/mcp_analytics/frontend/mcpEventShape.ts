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

// Keeps exactly the events that represent one real tool call. Two conditions:
// the IS NOT NULL drops shapeless events (HogQL's != is null-tolerant, so a
// NULL effective tool would otherwise pass the comparison and surface as a
// "None" bucket), and != 'exec' drops the single-exec dispatcher wrapper, which
// always pairs with an inner event for the real tool.
export const REAL_TOOL_CALL_HOGQL = `${EFFECTIVE_TOOL_HOGQL} IS NOT NULL AND ${EFFECTIVE_TOOL_HOGQL} != 'exec'`

export const REAL_TOOL_CALL_FILTER: HogQLPropertyFilter = {
    type: PropertyFilterType.HogQL,
    key: REAL_TOOL_CALL_HOGQL,
}
