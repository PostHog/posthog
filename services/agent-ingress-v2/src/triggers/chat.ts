/**
 * Chat trigger: POST /run starts a new session, POST /send appends to an
 * existing one, GET /listen streams events (SSE). Used by the in-PostHog chat
 * scene and any HTTP client that wants a thread-shaped conversation.
 */

import { Request, Response, Router } from 'express'

import { SessionQueue } from '@posthog/agent-shared-v2'

import { authorize, AuthProvider, principalsMatch, principalToSession, PUBLIC_ONLY_AUTH_PROVIDER } from '../auth'
import { SessionEventBus } from '../bus'
import { enqueueOrResume } from '../enqueue'
import { RevisionResolver } from '../resolver'
import { hasTrigger, resolveAgent } from './resolve'

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
        const resolved = await resolveAgent(deps.resolver, req)
        if (!resolved) {
            res.status(404).json({ error: 'no_agent' })
            return
        }
        if (!hasTrigger(resolved, 'chat')) {
            res.status(404).json({ error: 'no_chat_trigger' })
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
        const message = typeof req.body?.message === 'string' ? req.body.message : ''
        const externalKey = typeof req.body?.external_key === 'string' ? req.body.external_key : null
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
        const sessionId = typeof req.body?.session_id === 'string' ? req.body.session_id : ''
        const message = typeof req.body?.message === 'string' ? req.body.message : ''
        if (!sessionId || !message) {
            res.status(400).json({ error: 'session_id and message required' })
            return
        }
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
        const resolved = await resolveAgent(deps.resolver, req)
        if (!resolved) {
            res.status(404).json({ error: 'no_agent' })
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
        const sessionId = typeof req.body?.session_id === 'string' ? req.body.session_id : ''
        if (!sessionId) {
            res.status(400).json({ error: 'session_id required' })
            return
        }
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
        const sessionId = String(req.query.session_id ?? '')
        if (!sessionId) {
            res.status(400).end()
            return
        }
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
