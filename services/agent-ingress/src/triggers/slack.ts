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
    HttpFetcher,
    IdentityStore,
    IntegrationStore,
    SessionPrincipal,
    SessionQueue,
    SLACK_BOT_TOKEN_KEY,
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
    /**
     * Outbound HTTP for the Slack identity bridge's `users.info` lookup.
     * Wired from the ingress entrypoint so the call dispatches through
     * smokescreen in prod alongside every other fetch. Optional — falls
     * back to a direct HttpClient when absent (harness path).
     */
    http?: HttpFetcher
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
            const slackConfig =
                slackTrigger && 'config' in slackTrigger
                    ? (slackTrigger.config as {
                          trusted_workspaces?: string[] | '*'
                          mention_only?: boolean
                          auto_resume_threads?: boolean
                      })
                    : ({} as {
                          trusted_workspaces?: string[] | '*'
                          mention_only?: boolean
                          auto_resume_threads?: boolean
                      })
            const trusted = slackConfig.trusted_workspaces
            const workspaceId = event.team ?? 'unknown'
            if (trusted !== '*' && (!Array.isArray(trusted) || !trusted.includes(workspaceId))) {
                res.status(403).json({ error: 'workspace_not_trusted', workspace: workspaceId })
                return
            }

            // mention_only / auto_resume_threads gate. Run BEFORE identity
            // resolution + the slack→posthog bridge so we don't pay an
            // identity-store write per dropped event when the bot is in a
            // busy channel.
            //
            // Semantics:
            //   - app_mention → always accepted (explicit @ to the bot).
            //   - message + mention_only=false → accepted (back-compat with
            //     bots that watch whole channels by design).
            //   - message + mention_only=true + auto_resume_threads=false →
            //     dropped. Plain channel chatter is noise.
            //   - message + mention_only=true + auto_resume_threads=true →
            //     accepted ONLY when thread_ts matches an existing session's
            //     external_key (so the conversation continues without
            //     re-@-mentioning every turn). Anything else dropped.
            //
            // The findByExternalKey lookup is a single indexed PG read against
            // `agent_session` — same cost as the existing /send resume path.
            const isAppMention = event.type === 'app_mention'
            const mentionOnly = slackConfig.mention_only ?? false
            const autoResumeThreads = slackConfig.auto_resume_threads ?? false
            const ackReaction = (slackConfig as { ack_reaction?: string }).ack_reaction
            // We need `externalKey` for both the gate and the enqueue below;
            // compute it once.
            const externalKey = `slack:${event.channel}:${event.thread_ts ?? event.ts}`
            // For non-mention events: track whether we're accepting because
            // the message is a reply in a thread the bot already owns. The
            // seed message surfaces this so the model can judge whether the
            // user is actually talking to it.
            let resumedOwnedThread = false
            if (!isAppMention && mentionOnly) {
                if (!autoResumeThreads || !event.thread_ts) {
                    res.json({ ok: true, dropped: 'mention_only' })
                    return
                }
                const existing = await deps.queue.findByExternalKey(resolved.application.id, externalKey)
                if (!existing) {
                    res.json({ ok: true, dropped: 'mention_only_no_owned_thread' })
                    return
                }
                resumedOwnedThread = true
            }

            // Fire-and-forget ack reaction. Posted to Slack right now — before
            // identity resolution + enqueue — so the user sees the emoji land
            // within Slack's 3s ack window even when the runner takes a
            // moment to claim the session. Fails open: a revoked / missing
            // bot token, a slack.com 5xx, a previously-reacted message
            // (`already_reacted`), or a missing channel must NOT break the
            // event handler. The `.catch` collapses every error path to a
            // silent no-op; the session still enqueues. We `void` rather
            // than `await` so reactions.add latency can't blow the ack
            // window.
            if (ackReaction) {
                void postAckReaction(deps, resolved.application, {
                    channel: event.channel,
                    ts: event.ts,
                    name: ackReaction,
                }).catch(() => undefined)
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
                        http: deps.http,
                    })
                }
            }

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
            //
            // `mention: true|false` tells the model whether THIS turn was an
            // explicit @-mention. Only emitted as `false` when the trigger
            // accepted a non-mention message via `auto_resume_threads` — the
            // user might be replying to the bot OR continuing a sidebar with
            // another human in the thread; the model has to judge intent
            // from the text + thread history before responding.
            const slackContext = [
                `[slack]`,
                `channel: ${event.channel}`,
                `ts: ${event.ts}`,
                `thread_ts: ${event.thread_ts ?? event.ts}`,
                `workspace: ${workspaceId}`,
                `user: ${event.user}`,
                `mention: ${isAppMention ? 'true' : 'false'}`,
                ...(resumedOwnedThread ? ['resumed_owned_thread: true'] : []),
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
 * Fire-and-forget `reactions.add` for the immediate-ack flow. Called from
 * the events handler when `slack.config.ack_reaction` is set; the surrounding
 * `void ... .catch(...)` collapses every error path to a silent no-op so
 * the session enqueue is never blocked. Resolves the bot token through the
 * same per-app encrypted_env resolver that handles the signing secret; if
 * the token is missing, drop the reaction silently (the agent might be
 * partway through punch-out, the gate is `mention_only`/auth — not this
 * cosmetic ack).
 */
async function postAckReaction(
    deps: SlackTriggerDeps,
    application: AgentApplication,
    opts: { channel: string; ts: string; name: string }
): Promise<void> {
    const token = await deps.signingSecretResolver.resolve(SLACK_BOT_TOKEN_KEY, application)
    if (!token) {
        return
    }
    // Skip if no HttpFetcher is wired. Production always passes one via
    // buildApp → triggerDeps.http; the harness opts into wiring per test so
    // an unsuspecting case doesn't accidentally hit real slack.com. The
    // outer `.catch` already guards against errors; this guard makes the
    // success path of the unconfigured case explicit (no-op).
    if (!deps.http) {
        return
    }
    const res = await deps.http.fetch('https://slack.com/api/reactions.add', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json; charset=utf-8',
        },
        body: JSON.stringify({ channel: opts.channel, timestamp: opts.ts, name: opts.name }),
    })
    // `already_reacted` is a normal outcome on retries — Slack delivers the
    // event up to 3 times if it doesn't see a 200 fast enough, and the
    // idempotency key downstream dedupes the enqueue but doesn't dedupe
    // this fire-and-forget call. Swallow it (and everything else) — the
    // outer `.catch` already does, but the explicit no-throw here means
    // the success path doesn't accidentally throw inside an async closure
    // we don't await.
    void res
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
