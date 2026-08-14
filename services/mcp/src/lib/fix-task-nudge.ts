import { MCP_ERROR_TRACKING_FIX_NUDGE_FLAG } from '@/lib/constants'
import type { EvaluatedFlags } from '@/lib/posthog/flags'

/**
 * Growth experiment: when an error tracking query tool returns issue detail or
 * stack traces, offer the calling agent the next step of staging an automated
 * fix through `tasks-create`. The offer rides the handler result as an
 * `_agentNote` (the established point-of-use guidance field) rather than the
 * tool description, because in single-exec mode descriptions only load on
 * `info <tool>` while the result always lands in the agent's context.
 *
 * Every condition fails closed:
 * - the `mcp-error-tracking-fix-nudge` flag must be on for the caller, so the
 *   experiment can roll out gradually and be killed without a deploy;
 * - `tasks-create` must be in the caller's resolved tool set (it is absent
 *   when the tasks feature, the required write scope, or a read-write
 *   connection is missing), so the nudge never points at an uncallable tool;
 * - the result must actually contain issue detail or events, so empty result
 *   sets and unknown response shapes get no nudge.
 */

/** The tool the nudge points at. It stages the fix task; opening the returned task URL starts the run. */
export const FIX_TASK_TOOL_NAME = 'tasks-create'

const SINGLE_ISSUE_NUDGE =
    'PostHog can attempt an automated fix for this issue as a background task. ' +
    `To stage one, call \`${FIX_TASK_TOOL_NAME}\` with \`description\` carrying the error message, stack trace, and the issue's \`_posthogUrl\` (add \`repository\` as "org/repo" when known), then open the returned task URL to start the run. ` +
    'Offer this to the user if they intend to fix the bug.'

const ISSUE_LIST_NUDGE =
    'PostHog can attempt an automated fix for any of these issues as a background task. ' +
    `To stage one, call \`${FIX_TASK_TOOL_NAME}\` with \`description\` carrying the chosen issue's name, \`_posthogUrl\`, and stack trace (add \`repository\` as "org/repo" when known), then open the returned task URL to start the run. ` +
    'Offer this to the user if they intend to fix one of these bugs.'

const FIX_TASK_NUDGES: Record<string, string> = {
    'query-error-tracking-issue': SINGLE_ISSUE_NUDGE,
    'query-error-tracking-issue-events': SINGLE_ISSUE_NUDGE,
    'query-error-tracking-issues-list': ISSUE_LIST_NUDGE,
}

/**
 * A result qualifies only when it demonstrably carries issue detail: the
 * detail tool's response has its required `id`, and the list/events tools'
 * standardized `{ results: [...] }` envelope is non-empty. Anything else
 * (errors never reach here, but also shape drift) gets no nudge.
 */
function hasIssueDetail(toolName: string, handlerResult: unknown): boolean {
    if (handlerResult === null || typeof handlerResult !== 'object') {
        return false
    }
    const record = handlerResult as Record<string, unknown>
    if (toolName === 'query-error-tracking-issue') {
        return typeof record.id === 'string' && record.id.length > 0
    }
    const results = record.results
    return Array.isArray(results) && results.length > 0
}

export interface FixTaskNudgeInput {
    /** The tool that produced the result (the inner tool name in exec mode, never `exec`). */
    toolName: string
    /** Raw handler return value, before serialization. */
    handlerResult: unknown
    /** Per-request evaluated flags; `undefined` means unevaluated, which fails closed. */
    featureFlags: EvaluatedFlags | undefined
    /** The caller's resolved tool set, already filtered by feature, scope, and read-only mode. */
    availableTools: ReadonlyArray<{ name: string }>
}

/**
 * Returns the fix-task nudge for a successful tool call, or `undefined` when
 * any gate fails. Callers attach it with `withAgentNote` so it reaches the
 * agent on every serialization path (exec text, `--json`, structuredContent).
 */
export function getFixTaskNudge({
    toolName,
    handlerResult,
    featureFlags,
    availableTools,
}: FixTaskNudgeInput): string | undefined {
    if (featureFlags?.[MCP_ERROR_TRACKING_FIX_NUDGE_FLAG] !== true) {
        return undefined
    }
    const nudge = FIX_TASK_NUDGES[toolName]
    if (!nudge) {
        return undefined
    }
    if (!hasIssueDetail(toolName, handlerResult)) {
        return undefined
    }
    if (!availableTools.some((tool) => tool.name === FIX_TASK_TOOL_NAME)) {
        return undefined
    }
    return nudge
}
