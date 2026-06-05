/**
 * Boot the ingress as a single Express app. The route table is one block —
 * triggers are siblings under the same /agents/<slug> prefix in path mode, or
 * mounted at root in domain mode.
 */

import express, { Express, Request, Response } from 'express'
import type { Pool } from 'pg'

import type { IdentityStore, IntegrationStore } from '@posthog/agent-shared'
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
import { asyncHandler, errorHandler } from './http-utils'
import { RevisionResolver, RoutingMode } from './resolver'

/**
 * The full set of trigger modules the ingress knows about. Each module is
 * self-describing — `router` for assembly, `routes` for `/schemas`. Adding a
 * new trigger means writing one module file and dropping it in this array;
 * mounting, schema publication, and auth advertisement all cascade.
 */
const TRIGGER_MODULES: TriggerModule[] = [chatTrigger, slackTrigger, webhookTrigger, mcpTrigger]

/**
 * Fallback resolver used when callers (mostly dev / harness paths) don't wire
 * a real one. Slack requests under such a setup get a clean
 * `signing_secret_unresolved` 500 instead of an obscure `Cannot read
 * properties of undefined`. Production wires a real `EncryptedFields`-backed
 * resolver — see services/agent-ingress/src/index.ts.
 */
const UNCONFIGURED_SLACK_SIGNING_SECRET_RESOLVER: import('../triggers/slack').SlackSigningSecretResolver = {
    async resolve(): Promise<string | null> {
        return null
    },
}

/**
 * Translate a route's auth kind into the concrete shape we publish to
 * callers. Resolved per-agent so the response says, e.g., "this route needs
 * a PAT" or "shared_secret in X-Acme-Secret header" — not just "uses agent
 * auth, look it up yourself."
 */
function resolveRouteAuth(kind: RouteAuthKind, specAuth: AgentSpec['auth']): Record<string, unknown> {
    if (kind === 'public') {
        return { mode: 'public' }
    }
    if (kind === 'slack_signing') {
        return { mode: 'slack_signing', header: 'X-Slack-Signature' }
    }
    // agent_spec — expose the accepted modes verbatim. Each mode is an
    // already-discriminated `{type, ...}` object; clients introspect to
    // pick a header / token shape they can send.
    return { modes: specAuth.modes }
}

export interface BuildAppOpts {
    revisions: RevisionStore
    queue: SessionQueue
    bus?: SessionEventBus
    teamId: number
    routingMode: RoutingMode
    domainSuffix?: string
    pathPrefix?: string
    /**
     * Resolves the Slack signing secret named by `slack.config.signing_secret_ref`
     * on the agent's spec. In production: pulls the entry from the agent's
     * `encrypted_env` via `EncryptedFields`. Optional only because chat/
     * webhook/mcp ignore it; if the spec configures a slack trigger and this
     * is absent, the slack trigger boots but every request 500s on
     * `signing_secret_unresolved`.
     */
    slackSigningSecretResolver?: import('../triggers/slack').SlackSigningSecretResolver
    authProvider?: AuthProvider
    /** Optional identity store — Slack trigger uses this to mint stable AgentUser ids. */
    identities?: IdentityStore
    /**
     * Shared secret with Django for the preview-proxy gate on non-live
     * revision invokes. When unset, the gate is bypassed (dev / harness).
     * See docs/agent-platform/plans/draft-preview-auth.md.
     */
    previewSecret?: string
    /**
     * Read-only access to PostHog's integration table. Slack trigger uses it
     * to fetch a workspace bot token for the Slack → PostHog user bridge
     * (#23 step 2). Optional — when absent, the bridge is skipped and
     * AgentUser.posthog_user_id stays null.
     */
    integrations?: IntegrationStore | null
    /**
     * Direct access to the posthog DB pool. Slack → PostHog user bridge
     * queries `posthog_user` by email. Optional — required only when
     * `integrations` is also set.
     */
    posthogDb?: Pool | null
    /**
     * Per-session credential broker. Ingress writes user auth materials
     * (OAuth bearer, PAT, JWT) here at /run + /send; the runner reads
     * via `ToolContext.credentials.resolve(target)`. Optional — when
     * absent each trigger router defaults to a fresh process-local
     * `MemoryCredentialBroker`, which works for tests that don't share
     * a broker between processes but loses creds on a worker restart.
     */
    credentialBroker?: import('@posthog/agent-shared').CredentialBroker
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
    // Slack interactivity posts `application/x-www-form-urlencoded` with a
    // `payload=<json>` field. The raw body is captured the same way so
    // signature verification can hash it.
    app.use(
        express.urlencoded({
            extended: false,
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
    // needs. Slack uses `signingSecretResolver`+`identities`; chat/webhook/mcp
    // ignore them. Centralising the assembly here keeps the registry uniform.
    const triggerDeps = {
        resolver,
        queue: opts.queue,
        teamId: opts.teamId,
        bus,
        authProvider,
        signingSecretResolver: opts.slackSigningSecretResolver ?? UNCONFIGURED_SLACK_SIGNING_SECRET_RESOLVER,
        identities: opts.identities,
        integrations: opts.integrations ?? null,
        posthogDb: opts.posthogDb ?? null,
        broker: opts.credentialBroker,
    }
    const mount = opts.routingMode === 'path' ? `${opts.pathPrefix ?? '/agents'}/:slug` : ''

    // Self-describing schemas. The response cascades from `spec.triggers` ∩
    // `TRIGGER_MODULES`: only modules whose type is configured on this agent
    // appear, and each route is rendered with its auth concretely resolved
    // against the agent's `spec.auth`. There is no hand-maintained map of
    // "which triggers have schemas" — it falls out of the module registry.
    app.get(
        `${mount}/schemas`,
        asyncHandler(async (req: Request, res: Response) => {
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
    )

    for (const m of TRIGGER_MODULES) {
        app.use(mount, m.router(triggerDeps))
    }

    // Last in the chain. Catches rejections from `asyncHandler`-wrapped
    // routes, translates ZodError / malformed JSON / AmbiguousRevisionError
    // into structured 400s, everything else into a JSON 500.
    app.use(errorHandler(log))
    return app
}
