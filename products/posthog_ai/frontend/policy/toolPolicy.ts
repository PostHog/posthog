import { isPostHogExecTool } from '../components/tool/posthogExecDisplay'
import { resolveToolCall } from '../components/tool/toolResolver'
import type { PermissionRequestRecord } from '../types/streamTypes'

// Re-exported so existing importers (and tests) keep resolving the exec-tool check from here.
export { isPostHogExecTool } from '../components/tool/posthogExecDisplay'

/**
 * Default sandbox tool-permission policy, ported from Twig
 * (`packages/agent/src/adapters/claude/permissions/posthog-exec-gate.ts`).
 *
 * The deployed agent-server runs in `default` mode and asks for approval on every PostHog `exec`
 * call. We mirror Twig's policy on the client instead: auto-approve every built-in (default) tool
 * and every PostHog `exec` operation EXCEPT the destructive ones (update/delete/destroy/
 * partial-update), which still surface the approval card. Non-PostHog MCP tools fall outside the
 * default-allow contract and also prompt.
 */

/** A sub-tool is destructive when one of these verbs appears as a whole `-`-bounded segment. */
const POSTHOG_DESTRUCTIVE_SUBTOOL_RE = /(^|-)(partial-update|update|delete|destroy)(-|$)/i

export function isPostHogDestructiveSubTool(subTool: string): boolean {
    return POSTHOG_DESTRUCTIVE_SUBTOOL_RE.test(subTool)
}

export type PermissionDecision = 'auto_allow' | 'prompt'

/** Read-only exec discovery verbs — safe to auto-approve since they never mutate PostHog data. */
const POSTHOG_EXEC_READ_ONLY_KEYS = new Set([
    '__posthog_exec_tools__',
    '__posthog_exec_search__',
    '__posthog_exec_info__',
    '__posthog_exec_schema__',
])

/**
 * Decide whether a permission request can be auto-approved or must prompt the user. The policy fails
 * closed: a request only auto-approves when it is positively identified as safe.
 *
 * PostHog `exec` is detected by canonical tool name and by the parsed verb/sub-tool (robust to a
 * missing `_meta.claudeCode.toolName`): read-only discovery verbs (`tools`/`search`/`info`/`schema`)
 * and non-mutating `call <sub-tool>`s auto-approve; mutating sub-tools prompt, and an exec call whose
 * sub-tool can't be resolved (malformed, unknown verb, unrecognized flags) prompts rather than
 * silently allowing. A positively-identified built-in (non-MCP tool with a canonical name)
 * auto-approves; other MCP servers and any frame we can't identify prompt.
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
        if (POSTHOG_EXEC_READ_ONLY_KEYS.has(resolvedKey)) {
            return 'auto_allow'
        }
        // A resolved `call <sub-tool>`: auto-approve only non-mutating sub-tools.
        if (innerToolName) {
            return isPostHogDestructiveSubTool(innerToolName) ? 'prompt' : 'auto_allow'
        }
        // Exec call we couldn't resolve to a concrete sub-tool — fail closed.
        return 'prompt'
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
