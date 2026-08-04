import { isPostHogExecTool } from '../components/tool/posthogExecDisplay'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { resolveToolCall } from '../utils/toolResolver'

// Re-exported so existing importers (and tests) keep resolving the exec-tool check from here.
export { isPostHogExecTool } from '../components/tool/posthogExecDisplay'

/**
 * Client-side sandbox tool-permission policy.
 *
 * The agent-server relays a permission request here in two cases: the exec sub-tool matched the
 * server's `--posthogExecPermissionRegex` (relayed in every non-background run regardless of
 * permission mode — see `POSTHOG_EXEC_PERMISSION_REGEX` in `products/tasks/backend/constants.py`,
 * which must stay in sync with the destructive verbs and persist tools below), or the run's
 * permission mode relays manual approvals and a client is connected. This policy decides which
 * relayed requests auto-approve and which surface the approval card: built-ins and read-only
 * PostHog `exec` auto-approve; destructive sub-tools prompt; persist/publish sub-tools prompt only
 * on foreground streams; full-auto (`bypassPermissions`) runs answer everything.
 */

/** Full-auto modes answer every relayed tool request without prompting (questions and plan approvals still surface). */
export function isFullAutoMode(mode: string | null | undefined): boolean {
    return mode === 'bypassPermissions'
}

/** A sub-tool is destructive when one of these verbs appears as a whole `-`-bounded segment. */
const POSTHOG_DESTRUCTIVE_SUBTOOL_RE = /(^|-)(partial-update|update|patch|delete|destroy)(-|$)/i

/**
 * Destructive-annotated sub-tools whose names carry no destructive verb segment (publish, ship,
 * merge, archive, …). Mirrors `POSTHOG_EXEC_DESTRUCTIVE_SUB_TOOLS` in
 * `products/tasks/backend/constants.py`, which a backend test keeps complete against the
 * `annotations.destructive: true` tools in `products/*\/mcp/*.yaml` — update both together.
 */
const POSTHOG_DESTRUCTIVE_SUB_TOOLS = new Set([
    // confirmed_action tools register only `<name>-execute` (and `-prepare`); the bare name is
    // never a runtime tool, so the destructive `-execute` variant is what must be gated.
    'change-requests-approve-execute',
    'change-requests-reject-execute',
    'error-tracking-bypass-rules-create',
    'error-tracking-issues-merge-create',
    'error-tracking-issues-split-create',
    'error-tracking-suppression-rules-create',
    'experiment-ship-variant',
    'external-data-schemas-resync',
    'external-data-sources-repair-cdc-create',
    'heatmaps-saved-regenerate',
    'inbox-reports-bulk-set-state',
    'inbox-reports-set-state',
    'llma-prompt-label-set',
    'organization-enforce-2fa',
    'organization-enforce-2fa-execute',
    'scout-scratchpad-forget',
    'signals-scout-scratchpad-forget',
    'skill-archive',
    'user-interview-topics-remove-interviewee',
    'visual-review-runs-finalize-create',
    'web-analytics-path-cleaning-suggestions-apply',
    'workflows-discard-draft',
    'workflows-publish',
    'workflows-restore-revision',
    'workflows-test-run',
])

export function isPostHogDestructiveSubTool(subTool: string): boolean {
    return POSTHOG_DESTRUCTIVE_SUBTOOL_RE.test(subTool) || POSTHOG_DESTRUCTIVE_SUB_TOOLS.has(subTool.toLowerCase())
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

/**
 * Persist/publish sub-tools that must prompt when (and only when) the run is a foreground stream
 * (a run rendered in a surface the user is watching, see `foregroundStreamLogic`).
 * These aren't destructive, so `defaultPermissionDecision` still auto-approves them everywhere else
 * (background runs, headless runs, replays); the call site in `runStreamLogic`'s
 * `routePermissionRequest` forces the prompt path for foreground streams. Scoped to the product
 * families from the apply-back migration plan — every enabled tool that persists new content
 * (create/copy/add) or publishes to end users (launch/stop). To extend it, add the sub-tool name
 * here AND to `POSTHOG_EXEC_PERMISSION_REGEX` in `products/tasks/backend/constants.py` — the
 * server only relays sub-tools matching that regex, so a name missing there never reaches this
 * gate in modes that don't relay manual approvals.
 */
const PERSIST_PROMPT_SUB_TOOLS = new Set([
    'dashboard-create',
    'dashboard-create-text-tile',
    'dashboard-tile-copy',
    'dashboard-widgets-batch-add',
    'create-feature-flag',
    'feature-flags-copy-flags-create',
    'scheduled-changes-create',
    'survey-create',
    'survey-launch',
    'survey-stop',
    'cdp-functions-create',
    'workflows-create',
    'workflows-create-email-template',
])

/** Whether a permission request resolves to a create-family persist tool from `PERSIST_PROMPT_SUB_TOOLS`. */
export function isPersistPromptTool(record: PermissionRequestRecord): boolean {
    const { innerToolName } = resolveToolCall(record.rawToolCall)
    return innerToolName != null && PERSIST_PROMPT_SUB_TOOLS.has(innerToolName)
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
