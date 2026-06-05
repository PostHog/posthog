/**
 * Slack events trigger.
 *
 * Expects POST /agents/<slug>/slack/events with Slack's events-api payload.
 * Verifies the signing secret (X-Slack-Signature) when configured, then
 * enqueues an AgentSession using thread_ts as the externalKey so repeated
 * messages in the same thread resume a single agent session.
 */

import { createHmac, timingSafeEqual } from 'crypto'
import { Request, Response, Router } from 'express'
import type { Pool } from 'pg'
import { z } from 'zod'

import {
    AgentApplication,
    IdentityStore,
    IntegrationStore,
    SessionPrincipal,
    SessionQueue,
    SLACK_SIGNING_SECRET_KEY,
} from '@posthog/agent-shared'

import { bridgeSlackToPosthogUser } from '../auth/slack-posthog-bridge'
import { applyElevationDecline, applyElevationGrant, authorizeGrant } from '../enqueue/acl'
import { enqueueOrResume } from '../enqueue/enqueue'
import { asyncHandler } from '../routing/http-utils'
import { RevisionResolver } from '../routing/resolver'
import { hasTrigger, resolveAgent } from './resolve'
import { SlackEventBodySchema } from './slack.schemas'
import type { TriggerModule } from './types'

/**
 * Resolves a secret named by `secretKey` (conventional, from
 * `TRIGGER_REQUIRED_SECRETS`) out of the agent's `encrypted_env`. The concrete
 * impl decrypts via `EncryptedFields`; the harness wires an in-memory
 * fallback. Pattern reusable for any future "trigger-needs-secret" wiring.
 */
export interface SlackSigningSecretResolver {
    resolve(secretKey: string, application: AgentApplication): Promise<string | null>
}

export interface SlackTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    teamId: number
    signingSecretResolver: SlackSigningSecretResolver
    /** Optional identity store — when present, slack events resolve to a stable AgentUser. */
    identities?: IdentityStore
    /**
     * Optional integration store for fetching the team's Slack bot token.
     * When set (and `posthogDb` is also set), the slack-events handler runs
     * the Slack → PostHog user bridge after resolving the AgentUser so the
     * dispatcher (#23 step 3) can read `posthog_user_id` for per-asker
     * authorisation. Absent in dev / harness — the bridge is a no-op and
     * AgentUser.posthog_user_id stays null.
     */
    integrations?: IntegrationStore | null
    /** Direct posthog DB pool for the bridge's `posthog_user` email lookup. */
    posthogDb?: Pool | null
}

export function slackRouter(deps: SlackTriggerDeps): Router {
    const r = Router({ mergeParams: true })
    r.post(
        '/slack/events',
        asyncHandler(async (req: Request, res: Response) => {
            // Resolve the agent first — the URL slug picks it. The signing
            // secret lives at the conventional `SLACK_SIGNING_SECRET_KEY`
            // entry of the agent's `encrypted_env`; freeze-time validation
            // in the janitor rejects revisions whose application doesn't
            // have it set, so production traffic always finds a value.
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            if (!hasTrigger(resolved, 'slack')) {
                res.status(404).json({ error: 'no_slack_trigger' })
                return
            }
            const slackTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'slack')
            const signingSecret = await deps.signingSecretResolver.resolve(
                SLACK_SIGNING_SECRET_KEY,
                resolved.application
            )
            if (!signingSecret) {
                res.status(500).json({ error: 'signing_secret_unresolved' })
                return
            }
            if (!verifySlackSignature(req, signingSecret)) {
                res.status(401).json({ error: 'invalid_signature' })
                return
            }
            const body = req.body as {
                type?: string
                challenge?: string
                event?: SlackEvent
                event_id?: string
            }
            if (body.type === 'url_verification') {
                res.json({ challenge: body.challenge })
                return
            }
            const event = body.event
            // Accept both `message` (channel messages the bot is a member of)
            // and `app_mention` (someone @-mentioned the bot). Slack delivers
            // the latter even when a workspace only subscribed to mentions,
            // and the spec's `slack.config.mention_only` flag implies the
            // ingress was always meant to handle it — drop the original
            // message-only gate that silently 200'd every mention with no-op.
            if (!event || (event.type !== 'message' && event.type !== 'app_mention') || event.bot_id) {
                res.json({ ok: true })
                return
            }

            // Workspace trust check. trusted_workspaces is required in the spec:
            // an array gates on membership; `"*"` opens to any workspace.
            const trusted =
                slackTrigger && 'config' in slackTrigger
                    ? (slackTrigger.config as { trusted_workspaces?: string[] | '*' }).trusted_workspaces
                    : undefined
            const workspaceId = event.team ?? 'unknown'
            if (trusted !== '*' && (!Array.isArray(trusted) || !trusted.includes(workspaceId))) {
                res.status(403).json({ error: 'workspace_not_trusted', workspace: workspaceId })
                return
            }

            // Identity resolution: same (workspace, user) tuple resolves to the
            // same AgentUser across sessions.
            const principalId = `${workspaceId}:${event.user}`
            let agentUserId = principalId
            if (deps.identities) {
                const agentUser = await deps.identities.findOrCreate({
                    team_id: resolved.application.team_id,
                    application_id: resolved.application.id,
                    principal_kind: 'slack',
                    principal_id: principalId,
                    metadata: { workspace: workspaceId, slack_user: event.user },
                })
                agentUserId = agentUser.id
                // Slack → PostHog user bridge (#23 step 2). Runs the first
                // time we see this AgentUser; cached on the row afterwards.
                // Sync but tight-budgeted so a Slack hiccup can't blow past
                // Slack's 3s event ack window.
                if (deps.integrations && deps.posthogDb) {
                    await bridgeSlackToPosthogUser(agentUser, workspaceId, event.user, {
                        integrations: deps.integrations,
                        identities: deps.identities,
                        posthogDb: deps.posthogDb,
                    })
                }
            }

            const externalKey = `slack:${event.channel}:${event.thread_ts ?? event.ts}`
            const slackPrincipal: SessionPrincipal = {
                kind: 'slack',
                workspace_id: workspaceId,
                slack_user_id: event.user,
                agent_user_id: agentUserId,
            }
            // Embed the Slack envelope context in the seed message so the model
            // knows which channel/ts/thread_ts to use when calling Slack APIs.
            // Without this, the model only sees the raw text and has no way to
            // route replies back to the originating channel/thread. The header
            // is parseable + greppable; agent.md tells the model to use the
            // values verbatim for any reactions.add / chat.postMessage call.
            const slackContext = [
                `[slack]`,
                `channel: ${event.channel}`,
                `ts: ${event.ts}`,
                `thread_ts: ${event.thread_ts ?? event.ts}`,
                `workspace: ${workspaceId}`,
                `user: ${event.user}`,
                ``,
                event.text ?? '',
            ].join('\n')
            const outcome = await enqueueOrResume(
                { queue: deps.queue, teamId: deps.teamId },
                {
                    application: resolved.application,
                    revision: resolved.revision,
                    externalKey,
                    // Slack retries the events callback up to 3 times if it
                    // doesn't see a 200 within 3 seconds. Without an
                    // idempotency key, every retry appends a duplicate seed
                    // to `pending_inputs` and the runner replies N times to
                    // the same mention. `event_id` is Slack's per-event uuid
                    // — identical across retries, unique per real event —
                    // so it's the right key. Falls back to ts when an older
                    // payload shape doesn't carry event_id.
                    idempotencyKey: body.event_id ? `slack:event:${body.event_id}` : `slack:ts:${event.ts}`,
                    seed: {
                        role: 'user',
                        content: slackContext,
                        timestamp: Date.now(),
                        sender: slackPrincipal,
                    },
                    principal: slackPrincipal,
                    trigger: 'slack',
                    requesterDisplay: `slack:${workspaceId}:${event.user}`,
                }
            )
            if (outcome.kind === 'elevation_required') {
                // Slack expects 200 on the events callback — retrying with the
                // same payload would just re-record the elevation request. The
                // v1 elevation message (Slack blocks + interactivity handler)
                // lands here; for now we just acknowledge and let the audit
                // trail on the session row carry the rejection.
                res.json({
                    ok: true,
                    session_id: outcome.sessionId,
                    resumed: false,
                    elevation_required: true,
                    elevation_request_id: outcome.elevationRequestId,
                    owner_display: outcome.existingPrincipalDisplay,
                })
                return
            }
            res.json({ ok: true, session_id: outcome.sessionId, resumed: outcome.isResume })
        })
    )

    // Slack interactivity: button clicks on the elevation message land here.
    // Slack posts `application/x-www-form-urlencoded` with a `payload` field
    // carrying URL-encoded JSON. We resolve the agent via the URL slug to
    // find the right signing secret, verify, then dispatch.
    r.post(
        '/slack/interactivity',
        asyncHandler(async (req: Request, res: Response) => {
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            if (!hasTrigger(resolved, 'slack')) {
                res.status(404).json({ error: 'no_slack_trigger' })
                return
            }
            const signingSecret = await deps.signingSecretResolver.resolve(
                SLACK_SIGNING_SECRET_KEY,
                resolved.application
            )
            if (!signingSecret) {
                res.status(500).json({ error: 'signing_secret_unresolved' })
                return
            }
            if (!verifySlackSignature(req, signingSecret)) {
                res.status(401).json({ error: 'invalid_signature' })
                return
            }
            const rawPayload = (req.body as { payload?: string } | undefined)?.payload
            if (typeof rawPayload !== 'string') {
                res.status(400).json({ error: 'missing_payload' })
                return
            }
            let payload: SlackInteractivityPayload
            try {
                payload = JSON.parse(rawPayload) as SlackInteractivityPayload
            } catch {
                res.status(400).json({ error: 'invalid_payload' })
                return
            }
            const action = payload.actions?.[0]
            const decoded = action ? decodeElevationActionValue(action.value) : null
            if (!action || !decoded) {
                res.status(400).json({ error: 'no_elevation_action' })
                return
            }
            const { sessionId, requestId, decision } = decoded
            const session = await deps.queue.get(sessionId)
            if (!session) {
                res.status(404).json({ error: 'session_not_found' })
                return
            }
            const workspaceId = payload.team?.id ?? payload.user?.team_id ?? 'unknown'
            const clickerId = payload.user?.id ?? ''
            const clickerPrincipal: SessionPrincipal = {
                kind: 'slack',
                workspace_id: workspaceId,
                slack_user_id: clickerId,
                agent_user_id: await resolveSlackUserId(deps, session.application_id, workspaceId, clickerId),
            }
            const authz = authorizeGrant(session, requestId, clickerPrincipal)
            if (!authz.ok) {
                if (authz.reason === 'not_session_owner') {
                    // Slack's interactivity contract: 200 + an ephemeral message
                    // shows only to the clicking user without polluting the thread.
                    res.json({
                        response_type: 'ephemeral',
                        replace_original: false,
                        text: 'Only the session owner can decide this elevation request.',
                    })
                    return
                }
                if (authz.reason === 'request_not_pending') {
                    res.json({
                        response_type: 'ephemeral',
                        replace_original: false,
                        text: 'This elevation request has already been decided.',
                    })
                    return
                }
                res.status(404).json({ error: authz.reason })
                return
            }
            if (decision === 'grant') {
                const result = await applyElevationGrant(deps.queue, session, {
                    requestId,
                    granter: clickerPrincipal,
                })
                res.json({
                    response_type: 'in_channel',
                    replace_original: true,
                    text: `✓ Access granted to ${result.request.requester_display}.`,
                })
                return
            }
            if (decision === 'decline') {
                const declined = await applyElevationDecline(deps.queue, session, {
                    requestId,
                    decider: clickerPrincipal,
                })
                res.json({
                    response_type: 'in_channel',
                    replace_original: true,
                    text: `✗ Request from ${declined.requester_display} declined.`,
                })
                return
            }
            res.status(400).json({ error: 'unknown_decision' })
        })
    )

    return r
}

/**
 * Parse the opaque `value` Slack carries from the elevation message back to
 * the interactivity payload. We pack `(sessionId, requestId, decision)` into
 * one string so the button definition stays self-contained.
 */
export function encodeElevationActionValue(opts: {
    sessionId: string
    requestId: string
    decision: 'grant' | 'decline'
}): string {
    return `elevation:${opts.decision}:${opts.sessionId}:${opts.requestId}`
}

export function decodeElevationActionValue(
    value: string | undefined
): { sessionId: string; requestId: string; decision: 'grant' | 'decline' } | null {
    if (!value) {
        return null
    }
    const parts = value.split(':')
    if (parts.length !== 4 || parts[0] !== 'elevation') {
        return null
    }
    const decision = parts[1]
    if (decision !== 'grant' && decision !== 'decline') {
        return null
    }
    return { decision, sessionId: parts[2], requestId: parts[3] }
}

interface SlackInteractivityPayload {
    type?: string
    team?: { id?: string }
    user?: { id?: string; team_id?: string }
    actions?: Array<{ action_id?: string; value?: string }>
}

/**
 * Resolve a clicking Slack user to the same AgentUser id the events trigger
 * would produce for that user. When the identity store is wired this is a
 * stable lookup; without it we fall back to the raw `workspace:user` tuple
 * which matches what the events trigger persists.
 */
async function resolveSlackUserId(
    deps: SlackTriggerDeps,
    applicationId: string,
    workspaceId: string,
    userId: string
): Promise<string> {
    const principalId = `${workspaceId}:${userId}`
    if (!deps.identities) {
        return principalId
    }
    const agentUser = await deps.identities.findOrCreate({
        team_id: deps.teamId,
        application_id: applicationId,
        principal_kind: 'slack',
        principal_id: principalId,
        metadata: { workspace: workspaceId, slack_user: userId },
    })
    return agentUser.id
}

interface SlackEvent {
    type: string
    channel: string
    user: string
    team?: string
    text?: string
    ts: string
    thread_ts?: string
    bot_id?: string
}

export function verifySlackSignature(req: Request, signingSecret: string): boolean {
    const ts = req.headers['x-slack-request-timestamp']
    const sig = req.headers['x-slack-signature']
    if (typeof ts !== 'string' || typeof sig !== 'string') {
        return false
    }
    const now = Math.floor(Date.now() / 1000)
    if (Math.abs(now - parseInt(ts, 10)) > 60 * 5) {
        return false
    }
    const raw = ((req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body)) as string
    const base = `v0:${ts}:${raw}`
    const mac = createHmac('sha256', signingSecret).update(base).digest('hex')
    const expected = `v0=${mac}`
    if (sig.length !== expected.length) {
        return false
    }
    return timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
}

/** Published `bodySchema` covers only the two envelope shapes we route on
 *  (`url_verification`, `event_callback`). The runtime handler is permissive
 *  — Slack sends a long tail of event types we accept-and-no-op, so we
 *  deliberately don't safeParse against the published schema. Callers
 *  authoring against the schema get the contract; Slack's real traffic
 *  doesn't get rejected. */
export const slackTrigger: TriggerModule = {
    type: 'slack',
    router: slackRouter,
    routes: [
        {
            method: 'POST',
            path: '/slack/events',
            bodySchema: z.toJSONSchema(SlackEventBodySchema),
            auth: 'slack_signing',
        },
        {
            method: 'POST',
            path: '/slack/interactivity',
            // Slack posts urlencoded `payload=<json>` — published schema is the
            // decoded JSON so authoring tools see the actual interactivity
            // contract, not just an opaque form-data envelope.
            bodySchema: z.toJSONSchema(z.object({ payload: z.string() })),
            auth: 'slack_signing',
        },
    ],
}
