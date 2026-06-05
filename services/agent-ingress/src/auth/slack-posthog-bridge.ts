/**
 * Slack identity → PostHog user bridge.
 *
 * When the ingress sees a never-before-seen Slack user, this helper:
 *   1. Fetches the team's Slack bot token via the integration store.
 *      Slack stores one integration per workspace; integration_id IS the
 *      workspace_id (e.g. `T01ABC`), so the lookup is direct.
 *   2. Calls `slack.users.info` to fetch the user's profile email.
 *   3. Queries `posthog_user` by lowered email.
 *   4. Caches the result on the AgentUser row via `setPosthogUserId`. A
 *      successful match stores the user_id; a deliberate miss (no Slack
 *      token, no email, no matching posthog_user) stores `null` so
 *      subsequent events skip the remote call.
 *
 * The bridge is called inside the slack-events handler. Slack expects
 * events to be ack'd within 3 seconds — keep the lookup synchronous (so
 * the dispatcher sees the cached value on the immediate next turn) but
 * apply a tight timeout so a Slack/PG hiccup can't block ingress under
 * load.
 *
 * Per-asker authorisation in the dispatcher (#23 step 3) reads
 * `AgentUser.posthog_user_id` to resolve the calling user's
 * OrganizationMembership level.
 */

import type { Pool } from 'pg'

import { AgentUser, HttpClient, HttpFetcher, IdentityStore, IntegrationStore } from '@posthog/agent-shared'

const SLACK_USERS_INFO_URL = 'https://slack.com/api/users.info'

/** Default upper bound on the round-trip. Slack typically responds in <300ms. */
const DEFAULT_TIMEOUT_MS = 2_000

export interface BridgeSlackUserDeps {
    integrations: IntegrationStore
    identities: IdentityStore
    posthogDb: Pool
    /**
     * Override the Slack API call. Tests inject a stub; prod uses the real
     * `fetch` against `slack.com/api/users.info`.
     */
    fetchSlackEmail?: (token: string, slackUserId: string, signal: AbortSignal) => Promise<string | null>
    /**
     * Outbound HTTP client for the default fetcher. Defaults to a direct
     * HttpClient when omitted — wire from the ingress entrypoint so the
     * Slack lookup dispatches through smokescreen in prod. Ignored when
     * `fetchSlackEmail` is set (tests).
     */
    http?: HttpFetcher
    timeoutMs?: number
}

/**
 * Bridge a single (workspace, slack_user) pair. Idempotent — if the
 * AgentUser already has a `posthog_user_id` set, returns it unchanged. On
 * lookup failure stamps `null` so the bridge doesn't re-run for the same
 * user on every event. Returns the resolved id (or null).
 */
export async function bridgeSlackToPosthogUser(
    agentUser: AgentUser,
    workspaceId: string,
    slackUserId: string,
    deps: BridgeSlackUserDeps
): Promise<number | null> {
    if (agentUser.posthog_user_id !== undefined && agentUser.posthog_user_id !== null) {
        return agentUser.posthog_user_id
    }
    // `posthog_user_id === null` means "lookup already ran, no match." Don't
    // re-run unless someone explicitly invalidates the row.
    if (agentUser.posthog_user_id === null) {
        return null
    }

    const timeoutMs = deps.timeoutMs ?? DEFAULT_TIMEOUT_MS
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
        const credentials = await deps.integrations.get(agentUser.team_id, 'slack', workspaceId)
        if (!credentials?.access_token) {
            await deps.identities.setPosthogUserId(agentUser.id, null)
            return null
        }
        const http = deps.http ?? new HttpClient()
        const fetcher =
            deps.fetchSlackEmail ?? ((token, userId, signal) => defaultFetchSlackEmail(http, token, userId, signal))
        const email = await fetcher(credentials.access_token, slackUserId, ctrl.signal)
        if (!email) {
            await deps.identities.setPosthogUserId(agentUser.id, null)
            return null
        }
        const userId = await lookupPosthogUserByEmail(deps.posthogDb, email)
        await deps.identities.setPosthogUserId(agentUser.id, userId)
        return userId
    } catch {
        // Lookup blew up (timeout, Slack 5xx, PG hiccup). Don't stamp null —
        // the next event gets another chance once whatever broke recovers.
        return null
    } finally {
        clearTimeout(timer)
    }
}

async function defaultFetchSlackEmail(
    http: HttpFetcher,
    token: string,
    slackUserId: string,
    signal: AbortSignal
): Promise<string | null> {
    const res = await http.fetch(`${SLACK_USERS_INFO_URL}?user=${encodeURIComponent(slackUserId)}`, {
        method: 'GET',
        headers: { authorization: `Bearer ${token}` },
        signal,
    })
    if (!res.ok) {
        return null
    }
    const body = (await res.json()) as { ok?: boolean; user?: { profile?: { email?: string } } }
    if (!body.ok) {
        return null
    }
    return body.user?.profile?.email ?? null
}

async function lookupPosthogUserByEmail(pool: Pool, email: string): Promise<number | null> {
    const r = await pool.query<{ id: number }>(
        // posthog_user.email is stored lowercased on signup; compare case-
        // insensitively so a Slack profile with `Carol@Posthog.com` still
        // matches `carol@posthog.com`.
        `SELECT id FROM posthog_user WHERE lower(email) = lower($1) LIMIT 1`,
        [email]
    )
    return r.rowCount === 0 ? null : r.rows[0].id
}
