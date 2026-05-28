/**
 * Chat trigger: POST /run starts a new session, POST /send appends to an
 * existing one, GET /listen streams events (SSE). Used by the in-PostHog chat
 * scene and any HTTP client that wants a thread-shaped conversation.
 */

import { Request, Response, Router } from 'express'
import { z } from 'zod'

import { SessionQueue } from '@posthog/agent-shared'
import { SessionEventBus } from '@posthog/agent-shared'

import {
    authorize,
    AuthProvider,
    principalsMatch,
    principalToSession,
    PUBLIC_ONLY_AUTH_PROVIDER,
} from '../enqueue/auth'
import { enqueueOrResume } from '../enqueue/enqueue'
import { RevisionResolver } from '../routing/resolver'
import { ChatCancelBodySchema, ChatListenQuerySchema, ChatRunBodySchema, ChatSendBodySchema } from './chat.schemas'
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
}

export function chatRouter(deps: ChatTriggerDeps): Router {
    const r = Router({ mergeParams: true })

    r.post('/run', async (req: Request, res: Response) => {
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
        const sessionPrincipal = principalToSession(auth.principal)
        const { sessionId, isResume } = await enqueueOrResume(
            { queue: deps.queue, teamId: deps.teamId },
            {
                application: resolved.application,
                revision: resolved.revision,
                externalKey,
                seed: { role: 'user', content: message, timestamp: Date.now() },
                principal: sessionPrincipal,
            }
        )
        res.json({ ok: true, session_id: sessionId, resumed: isResume, principal: auth.principal })
    })

    r.post('/send', async (req: Request, res: Response) => {
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
        if (existing.state === 'completed' || existing.state === 'failed') {
            res.status(410).json({ error: 'session_terminal', state: existing.state })
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
        if (!principalsMatch(existing.principal, principalToSession(auth.principal))) {
            res.status(403).json({ error: 'principal_mismatch' })
            return
        }
        await deps.queue.appendPendingInput(sessionId, { role: 'user', content: message, timestamp: Date.now() })
        await deps.queue.update(sessionId, { state: 'queued' })
        res.json({ ok: true })
    })

    r.post('/cancel', async (req: Request, res: Response) => {
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
        if (existing.state === 'completed' || existing.state === 'failed') {
            res.json({ ok: true, idempotent: true, state: existing.state })
            return
        }
        await deps.queue.update(sessionId, { state: 'failed' })
        res.json({ ok: true })
    })

    r.get('/listen', async (req: Request, res: Response) => {
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
    ],
}
