/**
 * Chat trigger: POST /run starts a new session, POST /send appends to an
 * existing one, GET /listen streams events (SSE). Used by the in-PostHog chat
 * scene and any HTTP client that wants a thread-shaped conversation.
 */

import { Request, Response, Router } from 'express'
import { z } from 'zod'

import { CredentialBroker, MemoryCredentialBroker, SessionEventBus, SessionQueue } from '@posthog/agent-shared'

import { buildElevationResponse, principalDisplay, recordElevationRequest, requireAclAccess } from '../enqueue/acl'
import { authorize, AuthProvider, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { enqueueOrResume } from '../enqueue/enqueue'
import { asyncHandler } from '../routing/http-utils'
import { RevisionResolver } from '../routing/resolver'
import {
    ChatCancelBodySchema,
    ChatClientToolResultBodySchema,
    ChatListenQuerySchema,
    ChatRunBodySchema,
    ChatSendBodySchema,
} from './chat.schemas'
import { hasTrigger, resolveAgent } from './resolve'
import type { TriggerModule } from './types'

/**
 * Turn a zod error into the structured 400 body. Same shape as the janitor's
 * validation responses so callers (curl, MCP, tests) parse it uniformly.
 */
function badRequest(res: Response, err: z.ZodError): void {
    res.status(400).json({ error: 'invalid_body', issues: err.issues })
}

export interface ChatTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    bus: SessionEventBus
    teamId: number
    authProvider?: AuthProvider
    /**
     * Broker for per-session auth credentials. Default: a fresh
     * `MemoryCredentialBroker` so dev / tests work out of the box.
     * Prod wires a `RedisCredentialBroker` shared across services.
     */
    broker?: CredentialBroker
}

export function chatRouter(deps: ChatTriggerDeps): Router {
    const r = Router({ mergeParams: true })
    const broker = deps.broker ?? new MemoryCredentialBroker()

    r.post(
        '/run',
        asyncHandler(async (req: Request, res: Response) => {
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                // resolveAgent may have already written a 400 (ambiguous prefix).
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            if (!hasTrigger(resolved, 'chat')) {
                res.status(404).json({ error: 'no_chat_trigger' })
                return
            }
            const parsed = ChatRunBodySchema.safeParse(req.body)
            if (!parsed.success) {
                badRequest(res, parsed.error)
                return
            }
            const { message, external_key: externalKey = null } = parsed.data
            const auth = await authorize(
                req,
                resolved.application,
                resolved.revision.spec,
                deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
            )
            if (!auth.ok) {
                res.status(auth.status).json({ error: auth.reason })
                return
            }
            const sessionPrincipal = auth.principal
            const outcome = await enqueueOrResume(
                { queue: deps.queue, teamId: deps.teamId },
                {
                    application: resolved.application,
                    revision: resolved.revision,
                    externalKey,
                    seed: { role: 'user', content: message, timestamp: Date.now(), sender: sessionPrincipal },
                    principal: sessionPrincipal,
                    trigger: 'chat',
                    requesterDisplay: principalDisplay(sessionPrincipal),
                }
            )
            if (outcome.kind === 'elevation_required') {
                res.status(403).json({
                    error: 'elevation_required',
                    elevation_request_id: outcome.elevationRequestId,
                    session_id: outcome.sessionId,
                    owner_display: outcome.existingPrincipalDisplay,
                })
                return
            }
            // Write per-session auth materials into the broker keyed by
            // the freshly-minted session id. Tools resolve through this
            // at call time; nothing token-bearing lands on the session row.
            await broker.write(outcome.sessionId, auth.credentials)
            res.json({
                ok: true,
                session_id: outcome.sessionId,
                resumed: outcome.isResume,
                principal: auth.principal,
            })
        })
    )

    r.post(
        '/send',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = ChatSendBodySchema.safeParse(req.body)
            if (!parsed.success) {
                badRequest(res, parsed.error)
                return
            }
            const { session_id: sessionId, message } = parsed.data
            const existing = await deps.queue.get(sessionId)
            if (!existing) {
                res.status(404).json({ error: 'session_not_found' })
                return
            }
            // Strict principal match: re-authenticate against the agent's auth
            // mode and compare to the principal stored at /run time.
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                // resolveAgent may have already written a 400 (ambiguous prefix).
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            const auth = await authorize(
                req,
                resolved.application,
                resolved.revision.spec,
                deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
            )
            if (!auth.ok) {
                res.status(auth.status).json({ error: auth.reason })
                return
            }
            const incomingPrincipal = auth.principal
            const aclCheck = requireAclAccess(existing, incomingPrincipal)
            if (aclCheck.kind === 'denied') {
                const req = await recordElevationRequest(deps.queue, existing, {
                    requester: incomingPrincipal,
                    requesterDisplay: principalDisplay(incomingPrincipal),
                    trigger: 'chat',
                    proposedMessage: {
                        role: 'user',
                        content: message,
                        timestamp: Date.now(),
                        sender: incomingPrincipal,
                    },
                })
                res.status(403).json(buildElevationResponse(existing, req))
                return
            }
            // Terminal-state policy (see session-restart redesign):
            //   - `failed` / `cancelled`: always 410. Restarting either
            //     would likely just re-fail or re-cancel.
            //   - `closed`: 410 unless the chat trigger spec opts into
            //     `allow_restart`.
            //   - `completed` / `queued` / `running`: append the message,
            //     re-queue. `completed` is open by design.
            if (existing.state === 'failed' || existing.state === 'cancelled') {
                res.status(410).json({ error: 'session_terminal', state: existing.state })
                return
            }
            if (existing.state === 'closed') {
                const chatTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'chat')
                const allowRestart = chatTrigger?.type === 'chat' ? (chatTrigger.config.allow_restart ?? false) : false
                if (!allowRestart) {
                    res.status(410).json({ error: 'session_terminal', state: 'closed' })
                    return
                }
            }
            await deps.queue.appendPendingInput(sessionId, {
                role: 'user',
                content: message,
                timestamp: Date.now(),
                sender: incomingPrincipal,
            })
            await deps.queue.update(sessionId, { state: 'queued' })
            // Refresh broker creds with whatever the client just supplied —
            // OAuth tokens may have been rotated since /run, and the
            // worker may have evicted the prior entry.
            await broker.write(sessionId, auth.credentials)
            res.json({ ok: true })
        })
    )

    r.post(
        '/cancel',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = ChatCancelBodySchema.safeParse(req.body)
            if (!parsed.success) {
                badRequest(res, parsed.error)
                return
            }
            const { session_id: sessionId } = parsed.data
            const existing = await deps.queue.get(sessionId)
            if (!existing) {
                res.status(404).json({ error: 'session_not_found' })
                return
            }
            // Cancel is idempotent: terminal sessions return ok without changing state.
            if (existing.state === 'closed' || existing.state === 'failed' || existing.state === 'cancelled') {
                res.json({ ok: true, idempotent: true, state: existing.state })
                return
            }
            await deps.queue.update(sessionId, { state: 'cancelled' })
            res.json({ ok: true, state: 'cancelled' })
        })
    )

    r.get(
        '/listen',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = ChatListenQuerySchema.safeParse(req.query)
            if (!parsed.success) {
                badRequest(res, parsed.error)
                return
            }
            const { session_id: sessionId } = parsed.data
            res.setHeader('Content-Type', 'text/event-stream')
            res.setHeader('Cache-Control', 'no-cache')
            res.setHeader('Connection', 'keep-alive')
            res.flushHeaders()
            const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
                res.write(`data: ${JSON.stringify(event)}\n\n`)
            })
            req.on('close', () => unsubscribe())
        })
    )

    /**
     * Receive a client-tool result the connecting client computed in
     * response to a runner-emitted `client_tool_call` event. Publishes
     * a `client_tool_result` bus event with the same `call_id`; the
     * runner's per-session subscriber (set up in `loop/driver.ts`)
     * resolves the matching pending promise so the model turn unblocks.
     */
    r.post(
        '/client_tool_result',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = ChatClientToolResultBodySchema.safeParse(req.body)
            if (!parsed.success) {
                badRequest(res, parsed.error)
                return
            }
            const { session_id: sessionId, call_id, result, error } = parsed.data
            const existing = await deps.queue.get(sessionId)
            if (!existing) {
                res.status(404).json({ error: 'no_session' })
                return
            }
            await deps.bus.publish({
                session_id: sessionId,
                kind: 'client_tool_result',
                data: error ? { call_id, error } : { call_id, result },
                ts: new Date().toISOString(),
            })
            res.json({ ok: true })
        })
    )

    return r
}

/**
 * Self-description of the chat trigger's HTTP surface. The ingress reads this
 * to auto-publish the agent's API via `GET /agents/<slug>/schemas` — there's
 * no separate place that has to be kept in sync with the handlers above.
 */
export const chatTrigger: TriggerModule = {
    type: 'chat',
    router: chatRouter,
    routes: [
        {
            method: 'POST',
            path: '/run',
            bodySchema: z.toJSONSchema(ChatRunBodySchema),
            auth: 'agent_spec',
        },
        {
            method: 'POST',
            path: '/send',
            bodySchema: z.toJSONSchema(ChatSendBodySchema),
            auth: 'agent_spec',
        },
        {
            method: 'POST',
            path: '/cancel',
            bodySchema: z.toJSONSchema(ChatCancelBodySchema),
            auth: 'agent_spec',
        },
        {
            method: 'GET',
            path: '/listen',
            querySchema: z.toJSONSchema(ChatListenQuerySchema),
            auth: 'agent_spec',
        },
        {
            method: 'POST',
            path: '/client_tool_result',
            bodySchema: z.toJSONSchema(ChatClientToolResultBodySchema),
            auth: 'agent_spec',
        },
    ],
}
