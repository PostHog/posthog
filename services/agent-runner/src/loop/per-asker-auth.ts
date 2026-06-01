/**
 * Per-asker authorization for approval-gated tools. Reads the sender of
 * the most recent user message in the session conversation and resolves
 * "is this asker themselves in the approver scope?" — if so, the dispatcher
 * can dispatch the tool directly instead of queueing for someone else to
 * approve.
 *
 * Scopes supported in v0:
 *   - `team_admins` — the original B.2 v0 scope. Resolution:
 *     - `sender.kind === 'slack'`: `sender.id` is an `agent_user.id`. Look
 *       up the row, read its `posthog_user_id`, check OrganizationMembership
 *       for `level >= ADMIN`.
 *     - Other kinds: not authorised for v0. PAT-based self-authorisation
 *       (chat /run with an admin's token) is a sensible follow-up but adds
 *       a second resolution path that step 3 doesn't need to demo the
 *       Slack scenario.
 *   - `session_principal` (PR 7) — the session-owner-self-authorise case.
 *     Matches the most-recent user-turn sender against `session.principal`
 *     (auth-time identity stored on the session row) using the same strict
 *     `principalsMatch` comparison the trigger edge uses for /send. Stable
 *     across resume — a second user posting to a resumed session can't
 *     bypass the gate by being whoever-spoke-last. Per-asker fast-path
 *     only; queued-approval routing to the session principal widens later
 *     (see approval-gated-tools.md §6).
 *
 * See docs/agent-platform/plans/per-session-access-elevation.md for the
 * principal model, docs/agent-platform/plans/approval-gated-tools.md for
 * the queue path, and docs/agent-platform/plans/runtime-mcps.md "Resolved
 * design" decision B1 for the session_principal source choice.
 */

import type { Pool } from 'pg'

import { ConversationMessage, IdentityStore, principalsMatch, SessionPrincipal } from '@posthog/agent-shared'

/** PostHog's `OrganizationMembership.Level` values — keep in sync with the Django enum. */
const ADMIN_LEVEL = 8

/**
 * The check the dispatcher runs against the active session conversation.
 * Returns true when the most-recent user turn's sender satisfies one of the
 * scopes in `approverScope`. Returning false defers to the normal queue
 * path; the model never sees the difference.
 *
 * `sessionPrincipal` is the auth-time identity persisted on the session row
 * — used for the `session_principal` scope match. Null on sessions started
 * without auth on public agents; in that case `session_principal` is never
 * satisfied (nothing to compare against).
 */
export type IsAskerInApproverScope = (
    conversation: ConversationMessage[],
    teamId: number,
    approverScope: ReadonlyArray<string>,
    sessionPrincipal: SessionPrincipal | null
) => Promise<boolean>

export interface MakePerAskerAuthDeps {
    identities: IdentityStore
    posthogDb: Pool
}

/** Production factory — closes over the identity store + posthog DB pool. */
export function makePerAskerAuth(deps: MakePerAskerAuthDeps): IsAskerInApproverScope {
    return async (conversation, teamId, approverScope, sessionPrincipal) => {
        // `session_principal` is a pure equality check against the
        // auth-time principal on the session row — no DB roundtrip. Cheap;
        // check first so we don't burn a posthog DB query on every gated
        // call for a concierge-style spec.
        if (approverScope.includes('session_principal') && sessionPrincipal) {
            const sender = findLastUserSender(conversation)
            if (sender && principalsMatch(sessionPrincipal, sender)) {
                return true
            }
        }
        if (!approverScope.includes('team_admins')) {
            return false
        }
        const sender = findLastUserSender(conversation)
        if (!sender) {
            return false
        }
        const posthogUserId = await resolvePosthogUserId(sender, deps.identities)
        if (posthogUserId === null) {
            return false
        }
        return isTeamAdmin(deps.posthogDb, posthogUserId, teamId)
    }
}

/**
 * Walk the conversation back-to-front looking for the most recent user turn
 * with a `sender`. System-synthesised user messages (approval-decided
 * wakes, sweep-expired wakes) intentionally leave `sender` undefined and
 * are skipped — they aren't human asker actions.
 */
export function findLastUserSender(conversation: ConversationMessage[]): SessionPrincipal | null {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const m = conversation[i]
        if (m.role !== 'user') {
            continue
        }
        if (m.sender) {
            return m.sender
        }
    }
    return null
}

async function resolvePosthogUserId(sender: SessionPrincipal, identities: IdentityStore): Promise<number | null> {
    if (sender.kind !== 'slack' || !sender.agent_user_id) {
        return null
    }
    const agentUser = await identities.getById(sender.agent_user_id)
    if (!agentUser || agentUser.posthog_user_id == null) {
        return null
    }
    return agentUser.posthog_user_id
}

async function isTeamAdmin(pool: Pool, posthogUserId: number, teamId: number): Promise<boolean> {
    const r = await pool.query<{ one: number }>(
        // OrganizationMembership.Level: ADMIN=8, OWNER=15. The team belongs
        // to an organization; the membership scopes to that organization.
        `SELECT 1 AS one
         FROM posthog_organizationmembership om
         JOIN posthog_team t ON t.organization_id = om.organization_id
         WHERE om.user_id = $1 AND t.id = $2 AND om.level >= $3
         LIMIT 1`,
        [posthogUserId, teamId, ADMIN_LEVEL]
    )
    return (r.rowCount ?? 0) > 0
}
