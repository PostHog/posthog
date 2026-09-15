import { isPostHogExecTool } from '../components/tool/posthogExecDisplay'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { resolveToolCall } from '../utils/toolResolver'

// Re-exported so existing importers (and tests) keep resolving the exec-tool check from here.
export { isPostHogExecTool } from '../components/tool/posthogExecDisplay'

/**
 * Client-side sandbox tool-permission policy.
 *
 * The run's permission mode can relay manual approvals when a client is connected. This policy
 * auto-approves built-in tools and PostHog MCP calls in the task's project. It keeps approval cards
 * for connected-project calls, external MCP servers, and requests that cannot be identified.
 */

/** Whether the run auto-approves tools that stay inside its selected project. */
export function isFullAutoMode(mode: string | null | undefined): boolean {
    return mode === 'bypassPermissions'
}

export type PermissionDecision = 'auto_allow' | 'prompt'

const CONNECTED_PROJECT_SUB_TOOLS = new Set(['posthog-connection-call', 'posthog-connection-forward'])

function isConnectedProjectSubTool(subTool: string): boolean {
    return CONNECTED_PROJECT_SUB_TOOLS.has(subTool.toLowerCase())
}

export function isConnectedProjectTool(record: PermissionRequestRecord): boolean {
    const { innerToolName } = resolveToolCall(record.rawToolCall)
    return innerToolName != null && isConnectedProjectSubTool(innerToolName)
}

/**
 * Decide whether a permission request can be auto-approved or must prompt the user. The policy fails
 * closed: a request only auto-approves when it is positively identified as safe.
 *
 * PostHog `exec` is detected by canonical tool name and by the parsed command. Operations in the
 * task's project auto-approve. Connected-project calls, other MCP servers, and frames that cannot be
 * identified still prompt.
 */
export function defaultPermissionDecision(record: PermissionRequestRecord): PermissionDecision {
    // An `AskUserQuestion` rides the permission framework but is not an approval — auto-approving it
    // would pick the first option with no `answers`, which the agent rejects. Always prompt the user.
    if (record.questions?.length) {
        return 'prompt'
    }

    const { toolName } = record
    const { resolvedKey, innerToolName } = resolveToolCall(record.rawToolCall)

    const isExec = isPostHogExecTool(toolName) || innerToolName != null || resolvedKey.startsWith('__posthog_exec_')
    if (isExec) {
        if (innerToolName != null && isConnectedProjectSubTool(innerToolName)) {
            return 'prompt'
        }
        return 'auto_allow'
    }

    if (toolName.startsWith('mcp__')) {
        return 'prompt'
    }

    // A canonical name identifies a built-in (Bash, Edit, …); an empty name can't be identified.
    return toolName ? 'auto_allow' : 'prompt'
}

/** The optionId to auto-send when allowing — prefers the one-shot allow over `allow_always`. */
export function findAllowOptionId(record: PermissionRequestRecord): string | null {
    const allowOnce = record.options.find((o) => o.kind === 'allow_once')
    if (allowOnce) {
        return allowOnce.optionId
    }
    const anyAllow = record.options.find((o) => o.kind.startsWith('allow'))
    return anyAllow ? anyAllow.optionId : null
}
