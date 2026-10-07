import { isPostHogExecTool, parseExecCommand } from '../components/tool/posthogExecDisplay'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { resolveToolCall, UNPARSED_EXEC_KEY } from '../utils/toolResolver'

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

interface PermissionDecisionOptions {
    /**
     * `FEATURE_FLAGS.POSTHOG_AI_CHAT_ACTIONS`. With chat actions on, a click can ask for a destructive
     * workflow tool, so those calls get the approval card a typed request also gets.
     */
    chatActionsEnabled?: boolean
}

const CONNECTED_PROJECT_SUB_TOOLS = new Set(['posthog-connection-call', 'posthog-connection-forward'])

/** PostHog sub-tools that act on real people; the exec server never asks for confirmation itself. */
const DESTRUCTIVE_CHAT_ACTION_SUB_TOOLS = new Set(['workflows-enable', 'workflows-publish'])

const PUBLISH_PREVIEW_KEYS = new Set(['id', 'confirm', 'confirm_token'])

/**
 * A publish without `confirm: true` only previews its impact, so it needs no card. Only the exact
 * preview shape counts: the server lifts a payload wrapped under one key, so any other body might
 * carry a confirmed publish.
 */
function isPublishPreview(innerToolName: string, innerInput: unknown): boolean {
    if (innerToolName !== 'workflows-publish' || !isPlainObject(innerInput)) {
        return false
    }
    const keys = Object.keys(innerInput)
    return keys.every((key) => PUBLISH_PREVIEW_KEYS.has(key)) && !innerInput.confirm
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isConnectedProjectSubTool(subTool: string): boolean {
    return CONNECTED_PROJECT_SUB_TOOLS.has(subTool.toLowerCase())
}

/**
 * Whether a request needs the approval card while chat actions are on: it names a destructive
 * workflow tool, or it is a `call` whose sub-tool cannot be read and may name one behind a flag
 * this parser does not know. Full-auto checks this too, so both paths fail closed the same way.
 */
export function requiresChatActionApproval(record: PermissionRequestRecord): boolean {
    const { resolvedKey, innerToolName, innerInput } = resolveToolCall(record.rawToolCall)
    if (innerToolName != null) {
        const subTool = innerToolName.toLowerCase()
        return DESTRUCTIVE_CHAT_ACTION_SUB_TOOLS.has(subTool) && !isPublishPreview(subTool, innerInput)
    }
    return resolvedKey === UNPARSED_EXEC_KEY && isExecCallVerb(record)
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
export function defaultPermissionDecision(
    record: PermissionRequestRecord,
    options: PermissionDecisionOptions = {}
): PermissionDecision {
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
        return options.chatActionsEnabled && requiresChatActionApproval(record) ? 'prompt' : 'auto_allow'
    }

    if (toolName.startsWith('mcp__')) {
        return 'prompt'
    }

    // A canonical name identifies a built-in (Bash, Edit, …); an empty name can't be identified.
    return toolName ? 'auto_allow' : 'prompt'
}

function isExecCallVerb(record: PermissionRequestRecord): boolean {
    const command = record.rawToolCall.input.command
    return typeof command === 'string' && parseExecCommand(command).verb === 'call'
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
