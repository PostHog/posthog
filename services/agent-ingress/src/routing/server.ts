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
import type { AgentSpec } from '@posthog/agent-shared'

import { AuthProvider, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { chatTrigger } from '../triggers/chat'
import { mcpTrigger } from '../triggers/mcp'
import { resolveAgent } from '../triggers/resolve'
import { slackTrigger } from '../triggers/slack'
import type { RouteAuthKind, TriggerModule } from '../triggers/types'
import { webhookTrigger } from '../triggers/webhook'
import { AmbiguousRevisionError, RevisionResolver, RoutingMode } from './resolver'

/**
 * The full set of trigger modules the ingress knows about. Each module is
 * self-describing — `router` for assembly, `routes` for `/schemas`. Adding a
 * new trigger means writing one module file and dropping it in this array;
 * mounting, schema publication, and auth advertisement all cascade.
 */
const TRIGGER_MODULES: TriggerModule[] = [chatTrigger, slackTrigger, webhookTrigger, mcpTrigger]

/**
 * Translate a route's auth kind into the concrete shape we publish to
 * callers. Resolved per-agent so the response says, e.g., "this route needs
 * a PAT" or "shared_secret in X-Acme-Secret header" — not just "uses agent
 * auth, look it up yourself."
 */
function resolveRouteAuth(kind: RouteAuthKind, specAuth: AgentSpec['auth']): Record<string, string> {
    if (kind === 'public') {
        return { mode: 'public' }
    }
    if (kind === 'slack_signing') {
        return { mode: 'slack_signing', header: 'X-Slack-Signature' }
    }
    // agent_spec
    const out: Record<string, string> = { mode: specAuth.mode }
    if (specAuth.header) {
        out.header = specAuth.header
    }
    return out
}

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
    // Superset of every trigger's deps — each module's router picks what it
    // needs. Slack uses `signingSecret`+`identities`; chat/webhook/mcp ignore
    // them. Centralising the assembly here keeps the registry uniform.
    const triggerDeps = {
        resolver,
        queue: opts.queue,
        teamId: opts.teamId,
        bus,
        authProvider,
        signingSecret: opts.slackSigningSecret,
        identities: opts.identities,
    }
    const mount = opts.routingMode === 'path' ? `${opts.pathPrefix ?? '/agents'}/:slug` : ''

    // Self-describing schemas. The response cascades from `spec.triggers` ∩
    // `TRIGGER_MODULES`: only modules whose type is configured on this agent
    // appear, and each route is rendered with its auth concretely resolved
    // against the agent's `spec.auth`. There is no hand-maintained map of
    // "which triggers have schemas" — it falls out of the module registry.
    app.get(`${mount}/schemas`, async (req: Request, res: Response) => {
        const resolved = await resolveAgent(resolver, req, res)
        if (!resolved) {
            if (!res.headersSent) {
                res.status(404).json({ error: 'no_agent' })
            }
            return
        }
        const configured = new Set(resolved.revision.spec.triggers.map((t) => t.type))
        const triggers = TRIGGER_MODULES.filter((m) => configured.has(m.type)).map((m) => ({
            type: m.type,
            routes: m.routes.map((r) => ({
                method: r.method,
                path: r.path,
                ...(r.bodySchema ? { bodySchema: r.bodySchema } : {}),
                ...(r.querySchema ? { querySchema: r.querySchema } : {}),
                auth: resolveRouteAuth(r.auth, resolved.revision.spec.auth),
            })),
        }))
        res.json({
            agent: { slug: resolved.application.slug, name: resolved.application.name },
            triggers,
        })
    })

    for (const m of TRIGGER_MODULES) {
        app.use(mount, m.router(triggerDeps))
    }

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
