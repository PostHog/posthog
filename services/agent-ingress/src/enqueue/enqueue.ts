/**
 * One place to build + enqueue an AgentSession. Triggers call this with the
 * resolved (application, revision), the seed conversation message, and any
 * externalKey for dedupe.
 *
 * externalKey rule: if an existing session for (application, externalKey)
 * exists and is not terminal (`closed` / `failed`), the incoming principal
 * is checked against the session's ACL. If it passes, the new message is
 * appended to `pending_inputs` and the session is re-enqueued — the runner
 * drains pending_inputs at the start of its next turn, so this works whether
 * the session is currently `queued`, `running`, or `completed` (the
 * open-but-idle state under the new state machine).
 *
 * On ACL denial: the would-be message is preserved as a
 * `PendingElevationRequest` on the session, the session is NOT advanced,
 * and the result surfaces `elevation_required` to the trigger. The trigger
 * renders the appropriate denial response (HTTP 403 for chat/webhook/mcp,
 * 200 ack for Slack).
 *
 * principal: captured at session creation time. /send and Slack-thread
 * resumes both run the same ACL check via `requireAclAccess`.
 */

import { randomUUID } from 'crypto'

import {
    AgentApplication,
    AgentRevision,
    ConversationMessage,
    EMPTY_USAGE_TOTAL,
    SessionPrincipal,
    SessionQueue,
} from '@posthog/agent-shared'

import { ElevationTrigger, principalDisplay, recordElevationRequest, requireAclAccess } from './acl'

export interface EnqueueDeps {
    queue: SessionQueue
    teamId: number
}

export interface EnqueueInput {
    application: AgentApplication
    revision: AgentRevision
    externalKey: string | null
    seed: ConversationMessage
    principal?: SessionPrincipal | null
    /**
     * Used to attribute denied resumes to the trigger that produced them.
     * Defaults to 'chat' so callers that don't care (e.g. fresh sessions
     * via mcp tools/call) don't have to thread the field.
     */
    trigger?: ElevationTrigger
    /**
     * Human label for the rejected requester, displayed in elevation surfaces.
     * Defaults to `principalDisplay(principal)`.
     */
    requesterDisplay?: string
    /**
     * General-purpose dedupe key — "same request, return the original session
     * id on collision." Distinct from `externalKey` (which appends on
     * collision). Set by cron firings (`cron:<rev>:<name>:<minute>`) and
     * webhook redeliveries (provider-supplied keys like Stripe's
     * `Idempotency-Key` header). See `cron-trigger-scheduler.md` §6.
     *
     * If a session with this key already exists, this call no-ops and
     * returns `{ kind: 'created', isResume: false }` with the original
     * session id. The principal + seed message of the duplicate request
     * are discarded — same shape Stripe's idempotency contract follows.
     */
    idempotencyKey?: string
    /**
     * Trigger-specific metadata stamped on the session row at creation.
     * Forwarded straight to `AgentSession.trigger_metadata` JSONB.
     * Surfaced by `/sessions/list` so the UI can render a "fired by
     * <cron_name> at <fired_at>" badge etc.
     */
    triggerMetadata?: Record<string, unknown>
}

export type EnqueueOutcome =
    | { kind: 'created'; sessionId: string; isResume: false }
    | { kind: 'resumed'; sessionId: string; isResume: true }
    | {
          kind: 'elevation_required'
          sessionId: string
          isResume: false
          elevationRequestId: string
          existingPrincipalDisplay: string
      }

export async function enqueueOrResume(deps: EnqueueDeps, input: EnqueueInput): Promise<EnqueueOutcome> {
    // Idempotency check first — independent of externalKey. A duplicate
    // request returns the original session id unchanged; the principal +
    // seed of the duplicate are deliberately discarded. Stripe-shaped
    // semantics, same contract every other idempotent API in the platform
    // will eventually share.
    if (input.idempotencyKey) {
        const existing = await deps.queue.findByIdempotencyKey(input.application.id, input.idempotencyKey)
        if (existing) {
            return { kind: 'created', sessionId: existing.id, isResume: false }
        }
    }
    if (input.externalKey) {
        const existing = await deps.queue.findByExternalKey(input.application.id, input.externalKey)
        if (existing && existing.state !== 'closed' && existing.state !== 'failed') {
            const incoming = input.principal ?? null
            const check = requireAclAccess(existing, incoming)
            if (check.kind === 'denied') {
                const req = await recordElevationRequest(deps.queue, existing, {
                    requester: incoming,
                    requesterDisplay: input.requesterDisplay ?? principalDisplay(incoming),
                    trigger: input.trigger ?? 'chat',
                    proposedMessage: input.seed,
                })
                return {
                    kind: 'elevation_required',
                    sessionId: existing.id,
                    isResume: false,
                    elevationRequestId: req.id,
                    existingPrincipalDisplay: principalDisplay(existing.principal),
                }
            }
            await deps.queue.appendPendingInput(existing.id, input.seed)
            await deps.queue.update(existing.id, { state: 'queued' })
            return { kind: 'resumed', sessionId: existing.id, isResume: true }
        }
    }
    const session = {
        id: randomUUID(),
        application_id: input.application.id,
        revision_id: input.revision.id,
        team_id: deps.teamId,
        external_key: input.externalKey,
        idempotency_key: input.idempotencyKey ?? null,
        trigger_metadata: input.triggerMetadata ?? null,
        state: 'queued' as const,
        conversation: [input.seed],
        pending_inputs: [],
        principal: input.principal ?? null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    }
    try {
        await deps.queue.enqueue(session)
    } catch (err) {
        // Race-window safety net: between the `findByIdempotencyKey` check
        // above and this INSERT, a concurrent writer could have created a
        // session with the same key. The unique index fires; we surface the
        // original session id rather than the unique-violation error. Only
        // engaged when an idempotency key is supplied — without one the
        // unique index can't match.
        if (input.idempotencyKey && isUniqueViolation(err)) {
            const existing = await deps.queue.findByIdempotencyKey(input.application.id, input.idempotencyKey)
            if (existing) {
                return { kind: 'created', sessionId: existing.id, isResume: false }
            }
        }
        throw err
    }
    return { kind: 'created', sessionId: session.id, isResume: false }
}

/**
 * Postgres unique-violation SQLSTATE. `pg` surfaces this as `err.code`;
 * tests passing in arbitrary mocks can match the same shape by setting
 * `.code = '23505'` on the rejected error.
 */
function isUniqueViolation(err: unknown): boolean {
    return typeof err === 'object' && err !== null && (err as { code?: string }).code === '23505'
}
