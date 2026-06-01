/**
 * Per-asker authorization for approval-gated tools. Reads the sender of
 * the most recent user message in the session conversation and resolves
 * "is this asker themselves in the approver scope?" — if so, the dispatcher
 * can dispatch the tool directly instead of queueing for someone else to
 * approve.
 *
 * v0 supports only the `team_admins` scope (matching B.2 v0). Resolution:
 *   - `sender.kind === 'slack'`: `sender.id` is an `agent_user.id`. Look
 *     up the row, read its `posthog_user_id`, check OrganizationMembership
 *     for `level >= ADMIN`.
 *   - Other kinds: not authorised for v0. PAT-based self-authorisation
 *     (chat /run with an admin's token) is a sensible follow-up but adds a
 *     second resolution path that step 3 doesn't need to demo the Slack
 *     scenario.
 *
 * See docs/agent-platform/plans/per-session-access-elevation.md for the
 * principal model and B.2 (approval-gated-tools.md) for the queue path.
 */

import type { Pool } from 'pg'

import { ConversationMessage, IdentityStore, SessionPrincipal } from '@posthog/agent-shared'

/** PostHog's `OrganizationMembership.Level` values — keep in sync with the Django enum. */
const ADMIN_LEVEL = 8

/**
 * The check the dispatcher runs against the active session conversation.
 * Returns true when the most-recent user turn's sender satisfies one of the
 * scopes in `approverScope`. Returning false defers to the normal queue
 * path; the model never sees the difference.
 */
export type IsAskerInApproverScope = (
    conversation: ConversationMessage[],
    teamId: number,
    approverScope: ReadonlyArray<string>
) => Promise<boolean>

export interface MakePerAskerAuthDeps {
    identities: IdentityStore
    posthogDb: Pool
}

/** Production factory — closes over the identity store + posthog DB pool. */
export function makePerAskerAuth(deps: MakePerAskerAuthDeps): IsAskerInApproverScope {
    return async (conversation, teamId, approverScope) => {
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
