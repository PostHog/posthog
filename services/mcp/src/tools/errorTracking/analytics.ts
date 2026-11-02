/**
 * Analytics properties identifying which error tracking issue a tool call touched.
 *
 * Without the issue ID, `$mcp_tool_call` can show that an agent fetched *an* issue,
 * but not which one. So a fetch cannot be followed to what happened to that issue
 * next: a status change, an assignment, a merge, or the error that stops recurring.
 *
 * The properties are plain server properties, not `$mcp_*` ones, because they are
 * specific to this product and the MCP Analytics SDK owns the `$mcp_*` namespace.
 *
 * Value-free by construction, the rule `execCommandAnalyticsProperties` states: an
 * ID is recorded only if it is a UUID, the shape every issue ID has. Anything else
 * is the agent's own text and is dropped rather than echoed into analytics.
 */

const RECORDABLE_ISSUE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Tools that name a single issue, mapped to the argument that holds its ID. */
const ISSUE_ID_ARG_BY_TOOL: Record<string, string> = {
    'query-error-tracking-issue': 'issueId',
    'query-error-tracking-issue-events': 'issueId',
    'error-tracking-issues-partial-update': 'id',
    'error-tracking-issues-assign-partial-update': 'id',
    'error-tracking-issues-merge-create': 'id',
}

const MERGE_TOOL = 'error-tracking-issues-merge-create'

function recordableIssueId(value: unknown): string | undefined {
    return typeof value === 'string' && RECORDABLE_ISSUE_ID.test(value) ? value.toLowerCase() : undefined
}

/**
 * Properties describing the issue a tool targeted: `error_tracking_issue_id`, plus
 * `error_tracking_merged_issue_ids` on a merge. On a merge the issue ID is the
 * target that survives, and the merged IDs are the issues folded into it.
 *
 * `args` is whatever the caller has: parsed tool arguments in direct mode, or the
 * output of `parseExecCallInnerArgs` in single-exec mode. Malformed input yields
 * no properties rather than throwing, because analytics must never break a tool call.
 */
export function errorTrackingIssueAnalyticsProperties(
    toolName: string | undefined,
    args: unknown
): Record<string, unknown> {
    const idArg = toolName ? ISSUE_ID_ARG_BY_TOOL[toolName] : undefined
    if (!idArg || args === null || typeof args !== 'object' || Array.isArray(args)) {
        return {}
    }
    const record = args as Record<string, unknown>
    const issueId = recordableIssueId(record[idArg])
    if (!issueId) {
        return {}
    }
    const mergedIds =
        toolName === MERGE_TOOL && Array.isArray(record.ids)
            ? record.ids.map(recordableIssueId).filter((id): id is string => id !== undefined)
            : []
    return {
        error_tracking_issue_id: issueId,
        ...(mergedIds.length > 0 ? { error_tracking_merged_issue_ids: mergedIds } : {}),
    }
}
