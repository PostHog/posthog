/**
 * Boot the ingress as a single Express app. The route table is one block —
 * triggers are siblings under the same /agents/<slug> prefix in path mode, or
 * mounted at root in domain mode.
 */

import express, { Express, NextFunction, Request, Response } from 'express'

import type { IdentityStore } from '@posthog/agent-shared'
import { createLogger, RevisionStore, SessionQueue } from '@posthog/agent-shared'

const log = createLogger('ingress')

import { SessionEventBus, MemorySessionEventBus } from '@posthog/agent-shared'

import { AuthProvider, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { chatRouter } from '../triggers/chat'
import { mcpRouter } from '../triggers/mcp'
import { slackRouter } from '../triggers/slack'
import { webhookRouter } from '../triggers/webhook'
import { AmbiguousRevisionError, RevisionResolver, RoutingMode } from './resolver'

export interface BuildAppOpts {
    revisions: RevisionStore
    queue: SessionQueue
    bus?: SessionEventBus
    teamId: number
    routingMode: RoutingMode
    domainSuffix?: string
    pathPrefix?: string
    slackSigningSecret?: string
    authProvider?: AuthProvider
    /** Optional identity store — Slack trigger uses this to mint stable AgentUser ids. */
    identities?: IdentityStore
    /**
     * Shared secret with Django for the preview-proxy gate on non-live
     * revision invokes. When unset, the gate is bypassed (dev / harness).
     * See docs/agent-platform/plans/draft-preview-auth.md.
     */
    previewSecret?: string
}

export function buildApp(opts: BuildAppOpts): Express {
    const app = express()
    const bus = opts.bus ?? new MemorySessionEventBus()
    const resolver = new RevisionResolver({
        revisions: opts.revisions,
        mode: opts.routingMode,
        domainSuffix: opts.domainSuffix,
        pathPrefix: opts.pathPrefix,
        teamId: opts.teamId,
        previewSecret: opts.previewSecret,
    })
    app.use(
        express.json({
            verify: (req: Request, _res, buf) => {
                ;(req as Request & { rawBody?: string }).rawBody = buf.toString('utf-8')
            },
        })
    )
    app.get('/healthz', (_req, res) => {
        res.json({ ok: true })
    })

    const authProvider = opts.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
    const triggerDeps = { resolver, queue: opts.queue, teamId: opts.teamId, bus, authProvider }
    const mount = opts.routingMode === 'path' ? `${opts.pathPrefix ?? '/agents'}/:slug` : ''
    app.use(mount, slackRouter({ ...triggerDeps, signingSecret: opts.slackSigningSecret, identities: opts.identities }))
    app.use(mount, webhookRouter(triggerDeps))
    app.use(mount, chatRouter(triggerDeps))
    app.use(mount, mcpRouter(triggerDeps))

    app.use((err: Error, req: Request, res: Response, _next: NextFunction) => {
        if (err instanceof AmbiguousRevisionError) {
            res.status(400).json({
                error: 'ambiguous_revision',
                prefix: err.prefix,
                application_id: err.applicationId,
                candidates: err.candidates,
                detail: 'Multiple revisions match this prefix; re-issue with a longer prefix or pass ?revision_id.',
            })
            return
        }
        log.error({ err: err.message, stack: err.stack, path: req.path, method: req.method }, 'unhandled')
        res.status(500).json({ error: 'internal_error' })
    })
    return app
}
