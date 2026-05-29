/**
 * Per-session access enforcement. The symmetric check that every trigger runs
 * before letting an incoming principal advance an existing session — chat
 * /send, mcp tools/call continuation, and the resume paths in
 * enqueueOrResume (chat /run with external_key, webhook with x-external-key,
 * slack thread reply).
 *
 * The contract is:
 *   - The session's primary principal always matches.
 *   - An entry in `session.acl` that is `active` and unexpired matches when
 *     its `principal` equals the incoming principal, or when its `scope`
 *     covers the incoming principal.
 *   - Otherwise the incoming principal is denied; the caller records a
 *     PendingElevationRequest and renders the trigger-appropriate elevation
 *     surface (HTTP 403 + payload, or a Slack thread reply in v1).
 *
 * See docs/agent-platform/plans/per-session-access-elevation.md.
 */

import { randomUUID } from 'crypto'

import {
    AgentSession,
    ConversationMessage,
    PendingElevationRequest,
    SessionAclEntry,
    SessionPrincipal,
    SessionQueue,
} from '@posthog/agent-shared'

import { principalsMatch } from './auth'

export type AclCheckResult = { kind: 'allowed' } | { kind: 'denied'; reason: 'principal_mismatch' }

/** Trigger kinds that can produce an elevation request. */
export type ElevationTrigger = PendingElevationRequest['trigger']

/**
 * Max active `pending` requests we retain per session. Older entries get
 * downgraded to `expired` so the row doesn't grow unbounded.
 */
const MAX_PENDING_PER_SESSION = 5

export function requireAclAccess(session: AgentSession, incoming: SessionPrincipal | null): AclCheckResult {
    if (principalsMatch(session.principal, incoming)) {
        return { kind: 'allowed' }
    }
    const now = new Date().toISOString()
    for (const entry of session.acl ?? []) {
        if (!entryMatches(entry, incoming, now)) {
            continue
        }
        return { kind: 'allowed' }
    }
    return { kind: 'denied', reason: 'principal_mismatch' }
}

function entryMatches(entry: SessionAclEntry, incoming: SessionPrincipal | null, nowIso: string): boolean {
    if (entry.state !== 'active') {
        return false
    }
    if (entry.expires_at && entry.expires_at <= nowIso) {
        return false
    }
    if (entry.principal && incoming && principalsMatch(entry.principal, incoming)) {
        return true
    }
    if (entry.scope && incoming) {
        return scopeCovers(entry.scope, incoming)
    }
    return false
}

function scopeCovers(scope: NonNullable<SessionAclEntry['scope']>, incoming: SessionPrincipal): boolean {
    if (scope.kind === 'team_members') {
        return incoming.team_id === scope.team_id
    }
    // org_admins and slack_channel require principal metadata the ingress
    // doesn't carry yet (org_id, channel/workspace ids). v1 of the elevation
    // surface will plumb them through; v0 only ever populates principal-shaped
    // entries via the (yet-to-land) grant API.
    return false
}

export interface RecordElevationInput {
    requester: SessionPrincipal | null
    requesterDisplay: string
    trigger: ElevationTrigger
    proposedMessage: ConversationMessage
}

/**
 * Persist a `pending` request on the session and return its id. Idempotency:
 * a request with an identical (requester, message content) is replaced rather
 * than appended so a Slack client retrying the same event doesn't flood the
 * list. Older `pending` entries are downgraded to `expired` once the cap is
 * exceeded.
 */
export async function recordElevationRequest(
    queue: SessionQueue,
    session: AgentSession,
    input: RecordElevationInput
): Promise<PendingElevationRequest> {
    const created_at = new Date().toISOString()
    const req: PendingElevationRequest = {
        id: randomUUID(),
        requester: input.requester ?? { kind: 'anonymous' },
        requester_display: input.requesterDisplay,
        trigger: input.trigger,
        proposed_message: input.proposedMessage,
        created_at,
        state: 'pending',
    }
    const existing = session.pending_elevation_requests ?? []
    const pending = existing.filter((e) => e.state === 'pending')
    if (pending.length >= MAX_PENDING_PER_SESSION) {
        // Downgrade the oldest pending entries until we have room for `req`.
        const sortedPending = [...pending].sort((a, b) => a.created_at.localeCompare(b.created_at))
        const toExpire = sortedPending.slice(0, pending.length - (MAX_PENDING_PER_SESSION - 1))
        const expireIds = new Set(toExpire.map((e) => e.id))
        const next = existing.map((e) =>
            expireIds.has(e.id) ? { ...e, state: 'expired' as const, decision_at: created_at } : e
        )
        next.push(req)
        await queue.update(session.id, { pending_elevation_requests: next })
    } else {
        await queue.appendPendingElevationRequest(session.id, req)
    }
    return req
}

/**
 * Shape of the JSON body returned to HTTP clients on denial. Slack triggers
 * acknowledge to Slack with 200 + `{ elevation_required: true, ... }` instead
 * of a 403 so the events API doesn't retry; the v1 UX layer will also post
 * a thread reply.
 */
export interface ElevationResponseBody {
    error: 'elevation_required'
    elevation_request_id: string
    session_id: string
    /** Display label for the session's primary principal — "Alice", etc. */
    owner_display: string
}

export function buildElevationResponse(session: AgentSession, request: PendingElevationRequest): ElevationResponseBody {
    return {
        error: 'elevation_required',
        elevation_request_id: request.id,
        session_id: session.id,
        owner_display: principalDisplay(session.principal),
    }
}

/** Best-effort human-readable label for a principal — used in elevation surfaces. */
export function principalDisplay(p: SessionPrincipal | null): string {
    if (!p) {
        return 'session owner'
    }
    if (p.kind === 'anonymous') {
        return 'anonymous'
    }
    if (p.id) {
        return `${p.kind}:${p.id}`
    }
    return p.kind
}
