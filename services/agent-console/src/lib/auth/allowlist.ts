/**
 * Team allowlist check for the agent console.
 *
 * Driven by `AGENT_CONSOLE_ALLOWED_TEAM_IDS` on `AgentConsoleConfig`.
 * When the list is empty (the default) the gate is disabled — anyone
 * with a working PostHog login can use the console. Set the env var to
 * restrict access to a curated set of teams (projects).
 *
 * Checked at two points:
 *   1. The OAuth callback — denial means the session cookie is never
 *      set, so the browser can't sneak in by reloading the page.
 *   2. Every `/api/auth/me` refresh — defense in depth so an admin
 *      removing a team from the allowlist mid-session signs the user
 *      out on next refresh, rather than letting an old sealed cookie
 *      keep working until expiry.
 *
 * Used by both the callback route and the me route — keep the logic in
 * one place so a regression on one path can't drift past the other.
 */

import type { AgentConsoleConfig } from '@/lib/config'

/**
 * Subset of the PostHog `/api/users/@me/` shape we read. We're
 * intentionally permissive — the real payload has many more fields, but
 * we only care about the user's current team for gating.
 */
export interface AllowlistCheckProfile {
    team?: { id?: number | null } | null
}

export interface AllowlistCheckResult {
    allowed: boolean
    /** Best-effort identifier from the profile, surfaced for logging + the
     *  "not authorized" error page so the operator knows what to add to the
     *  allowlist if they meant to. */
    teamId: number | null
    /** Human-readable reason when `allowed: false`. */
    reason?: string
}

/**
 * Pure check — no side effects, no I/O. Returns whether the user's
 * current team matches the configured allowlist.
 */
export function checkAccessAllowlist(
    profile: AllowlistCheckProfile,
    config: Pick<AgentConsoleConfig, 'allowedTeamIds'>
): AllowlistCheckResult {
    const teamId = extractTeamId(profile)
    const { allowedTeamIds } = config

    if (allowedTeamIds.length === 0) {
        return { allowed: true, teamId } // no gate
    }
    if (typeof teamId === 'number' && allowedTeamIds.includes(teamId)) {
        return { allowed: true, teamId }
    }
    return {
        allowed: false,
        teamId,
        reason: formatDenialReason(teamId, allowedTeamIds),
    }
}

function extractTeamId(profile: AllowlistCheckProfile): number | null {
    const id = profile.team?.id
    return typeof id === 'number' ? id : null
}

function formatDenialReason(teamId: number | null, allowedTeamIds: number[]): string {
    return `Your current team (${teamId ?? 'unknown'}) is not on the access allowlist for this agent console deployment (${allowedTeamIds.length} allowed team(s)).`
}
