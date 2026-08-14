import type { SelfDrivingStatus } from '@/api/client'
import { MCP_ERROR_TRACKING_SELF_DRIVING_NUDGE_FLAG } from '@/lib/constants'
import type { EvaluatedFlags } from '@/lib/posthog/flags'
import type { Context } from '@/tools/types'

/**
 * Growth experiment: when an error tracking query tool returns issue detail or
 * stack traces, tell the calling agent that self-driving can fix issues like
 * this proactively, but only when the team has a user-actionable setup gap.
 * The note rides the handler result as an `_agentNote` (the established
 * point-of-use guidance field) rather than the tool description, because in
 * single-exec mode descriptions only load on `info <tool>` while the result
 * always lands in the agent's context.
 *
 * Every condition fails closed:
 * - the `mcp-error-tracking-self-driving-nudge` flag must be on for the
 *   caller, so the experiment can roll out gradually and be killed without a
 *   deploy;
 * - the result must actually contain issue detail or events, so empty result
 *   sets and unknown response shapes get no note;
 * - the team's self-driving status must show a gap the user can close
 *   (autostart switched off, or no GitHub connection). Teams that are fully
 *   set up, quota-paused, or whose status cannot be read get no note.
 */

export type SelfDrivingGap = 'github_missing' | 'autostart_off'

export interface SelfDrivingNudge {
    note: string
    gap: SelfDrivingGap
}

const NUDGED_TOOLS = new Set([
    'query-error-tracking-issue',
    'query-error-tracking-issue-events',
    'query-error-tracking-issues-list',
])

const PITCH =
    'PostHog can fix issues like this proactively: self-driving researches new error tracking issues and opens pull requests for the team to review.'

const GAP_NOTES: Record<SelfDrivingGap, (settingsUrl: string) => string> = {
    github_missing: (settingsUrl) =>
        `${PITCH} This project has no GitHub connection, so self-driving cannot open those PRs yet. If the user wants proactive fixes, send them to ${settingsUrl} to connect GitHub and finish setup.`,
    autostart_off: (settingsUrl) =>
        `${PITCH} Self-driving is switched off for this team. If the user wants proactive fixes, send them to ${settingsUrl} to turn it back on.`,
}

/**
 * A result qualifies only when it demonstrably carries issue detail: the
 * detail tool's response has its required `id`, and the list/events tools'
 * standardized `{ results: [...] }` envelope is non-empty. Anything else
 * (errors never reach here, but also shape drift) gets no note.
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

/**
 * The single user-actionable gap the note should name, or `undefined` when
 * there is nothing to say. GitHub wins over the autostart switch because
 * flipping the switch does nothing while no repository is connected. A
 * quota-paused org gets no note: the missing piece there is billing headroom,
 * not setup, and autostart resumes on its own when the quota lifts.
 */
export function selectSelfDrivingGap(status: SelfDrivingStatus): SelfDrivingGap | undefined {
    if (status.quota_blocked) {
        return undefined
    }
    if (!status.github_connected) {
        return 'github_missing'
    }
    if (!status.autostart_enabled) {
        return 'autostart_off'
    }
    return undefined
}

interface SelfDrivingNudgeInput {
    /** The tool that produced the result (the inner tool name in exec mode, never `exec`). */
    toolName: string
    /** Raw handler return value, before serialization. */
    handlerResult: unknown
    /** Per-request evaluated flags; `undefined` means unevaluated, which fails closed. */
    featureFlags: EvaluatedFlags | undefined
}

/**
 * Returns the self-driving nudge for a successful tool call, or `undefined`
 * when any gate fails. Gates are ordered so the status endpoint is only read
 * (through the state manager's cache) for flag-on calls to the three error
 * tracking tools that returned real issue data. Callers attach the note with
 * `withAgentNote` so it reaches the agent on every serialization path (exec
 * text, `--json`, structuredContent).
 */
export async function maybeGetSelfDrivingNudge(
    context: Context,
    { toolName, handlerResult, featureFlags }: SelfDrivingNudgeInput
): Promise<SelfDrivingNudge | undefined> {
    if (featureFlags?.[MCP_ERROR_TRACKING_SELF_DRIVING_NUDGE_FLAG] !== true) {
        return undefined
    }
    if (!NUDGED_TOOLS.has(toolName)) {
        return undefined
    }
    if (!hasIssueDetail(toolName, handlerResult)) {
        return undefined
    }
    try {
        const projectId = await context.stateManager.getProjectId()
        const status = await context.stateManager.getOrFetchSelfDrivingStatus(projectId)
        if (!status) {
            return undefined
        }
        const gap = selectSelfDrivingGap(status)
        if (!gap) {
            return undefined
        }
        const settingsUrl = `${context.api.getProjectBaseUrl(projectId)}/inbox?utm_source=mcp&utm_medium=agent_nudge&utm_campaign=error_tracking_self_driving`
        return { note: GAP_NOTES[gap](settingsUrl), gap }
    } catch {
        return undefined
    }
}
