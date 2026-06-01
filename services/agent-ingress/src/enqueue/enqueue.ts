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
        // PR-2 of cron-trigger-scheduler.md wires the upsert-on-conflict path
        // that consumes these. v1 enqueues always create fresh keys (null)
        // since no caller forwards an idempotency key yet.
        idempotency_key: null,
        trigger_metadata: null,
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
    await deps.queue.enqueue(session)
    return { kind: 'created', sessionId: session.id, isResume: false }
}
