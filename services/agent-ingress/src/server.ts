import { type IncomingRequest, type RouteDeps, type RouteResult, route } from '@repo/ass-server'
import express, { Express, NextFunction, Request, Response } from 'ultimate-express'

import {
    ApplicationsRepository,
    SessionEvent,
    SessionQueueManager,
    collectDefaults,
    compileAgent,
    logger,
    metricsContentType,
    metricsText,
} from '@posthog/agent-core'

import type { RoutingMode } from './config'
import { RevisionResolver } from './resolver'
import { extractHost, extractSlugFromPath } from './routes/host'

export interface ServerDeps {
    queue: SessionQueueManager
    bus: import('@posthog/agent-core').SessionBus
    resolver: RevisionResolver
    repository: ApplicationsRepository
    domainSuffix: string
    /**
     * How tenants are identified on inbound requests. See `config.ts`. The
     * branch lives inside `handleAgentRequest` — in `domain` mode we read the
     * Host header; in `path` mode we expect `/agents/<slug>/...` and route()
     * sees the stripped remainder so it never has to know about the prefix.
     */
    routingMode: RoutingMode
    /**
     * Validate a bearer token for an agent that declares `auth: pat`. The
     * default implementation looks the token up against the resolved revision's
     * team `secret_api_token` / `secret_api_token_backup` columns via
     * `ApplicationsRepository.verifyTeamSecret`. Tests can override.
     */
    authenticatePat?: (teamId: number, token: string) => Promise<boolean>
}

export function buildServer(deps: ServerDeps): Express {
    collectDefaults()
    const app = express()

    // Use raw bytes for every body — ass-server's route() decides how to parse
    // each path (Slack needs raw bytes for signature verification, /run wants
    // JSON, /send wants JSON). Doing parsing here would break Slack.
    app.use(express.raw({ type: '*/*', limit: '512kb' }))

    app.use((req, _res, next) => {
        logger.debug('ingress request', { method: req.method, path: req.path })
        next()
    })

    // Infrastructure endpoints — handled before the wildcard so they bypass
    // tenant resolution. The parent's liveness probes hit these.
    app.get('/health', (_req, res) => res.json({ ok: true }))
    app.get('/status', (_req, res) =>
        res.json({
            service: 'agent-ingress',
            version: process.env.npm_package_version ?? 'dev',
            uptimeSeconds: Math.round(process.uptime()),
        })
    )
    app.get('/metrics', async (_req, res) => {
        res.set('content-type', metricsContentType())
        res.send(await metricsText())
    })

    // Everything else: resolve agent + delegate to ass-server.route().
    app.all('*', (req: Request, res: Response, next: NextFunction) => {
        void handleAgentRequest(req, res, deps).catch(next)
    })

    return app
}

async function handleAgentRequest(req: Request, res: Response, deps: ServerDeps): Promise<void> {
    // Resolve the tenant. `domain` mode uses the Host header (the prod model);
    // `path` mode uses a `/agents/<slug>/...` URL prefix (dev-friendly when a
    // wildcard subdomain isn't available, e.g. behind a Cloudflare Quick
    // Tunnel). Both branches end with a `ResolvedRevision` + the path that
    // `route()` should see (`pathForRoute`).
    let revision: import('@posthog/agent-core').ResolvedRevision | null
    let pathForRoute = req.path
    if (deps.routingMode === 'path') {
        const match = extractSlugFromPath(req.path)
        if (!match) {
            res.status(400).json({ error: 'path-mode expects /agents/<slug>/<route>' })
            return
        }
        revision = await deps.resolver.resolveSlug(match.slug)
        pathForRoute = match.remainder
    } else {
        const host = extractHost(req, deps.domainSuffix)
        if (!host) {
            res.status(400).json({ error: `host does not match ${deps.domainSuffix}` })
            return
        }
        revision = await deps.resolver.resolveDomain(host)
    }
    if (!revision) {
        res.status(404).json({ error: 'application not found' })
        return
    }
    if (revision.revisionState !== 'ready') {
        res.status(409).json({ error: `revision not ready (state=${revision.revisionState})` })
        return
    }

    const agent = compileAgent(revision)
    const incoming = normalizeRequest(req, pathForRoute)

    // Lazy-decrypt the encrypted env at most once per request. Slack signature
    // verification needs one entry from it; nothing else here cares yet.
    let envPromise: Promise<Record<string, string>> | null = null
    const loadSecret = async (name: string): Promise<string | null> => {
        envPromise = envPromise ?? deps.repository.decryptEnv(revision.applicationId)
        const env = await envPromise
        return env[name] ?? null
    }

    // Bind the team context — every PAT check is scoped to the team that
    // owns the resolved revision so a valid secret for team A can't be used
    // to talk to team B's agent.
    const verifyTeamSecret =
        deps.authenticatePat ?? ((teamId, token) => deps.repository.verifyTeamSecret(teamId, token))
    const routeDeps: RouteDeps = {
        loadSecret,
        authenticatePat: (token: string) => verifyTeamSecret(revision.teamId, token),
    }

    let result: RouteResult
    try {
        result = await route(agent, incoming, routeDeps)
    } catch (err) {
        logger.error('route() threw', { error: String(err), slug: agent.slug })
        res.status(500).json({ error: 'internal routing error' })
        return
    }

    await dispatchRouteResult(result, req, res, deps, revision)
}

function normalizeRequest(req: Request, pathOverride?: string): IncomingRequest {
    const headers: Record<string, string> = {}
    for (const [key, value] of Object.entries(req.headers)) {
        if (value === undefined) {
            continue
        }
        headers[key.toLowerCase()] = Array.isArray(value) ? (value[0] ?? '') : value
    }
    const query: Record<string, string> = {}
    for (const [k, v] of Object.entries(req.query)) {
        query[k] = Array.isArray(v) ? String(v[0]) : String(v)
    }
    const rawBody = Buffer.isBuffer(req.body) ? req.body : Buffer.alloc(0)
    return {
        method: req.method,
        path: pathOverride ?? req.path,
        query,
        headers,
        rawBody,
    }
}

async function dispatchRouteResult(
    result: RouteResult,
    req: Request,
    res: Response,
    deps: ServerDeps,
    revision: import('@posthog/agent-core').ResolvedRevision
): Promise<void> {
    switch (result.kind) {
        case 'reject':
            res.status(result.status).json(result.body)
            return

        case 'respond':
            if (result.headers) {
                for (const [k, v] of Object.entries(result.headers as Record<string, string>)) {
                    res.setHeader(k, v)
                }
            }
            if (typeof result.body === 'string') {
                res.status(result.status).send(result.body)
            } else {
                res.status(result.status).json(result.body)
            }
            return

        case 'enqueue':
            try {
                const initialState = {
                    messages: [],
                    pendingInputs: [],
                    initialInput: result.input,
                    turnCount: 0,
                }
                const sessionId = await deps.queue.createJob({
                    teamId: revision.teamId,
                    applicationId: revision.applicationId,
                    revisionId: revision.revisionId,
                    queueName: 'default',
                    state: Buffer.from(JSON.stringify(initialState), 'utf8'),
                })
                res.status(202).json({ sessionId, trigger: result.trigger })
            } catch (err) {
                logger.error('enqueue failed', { error: String(err) })
                res.status(503).json({ error: 'enqueue failed' })
            }
            return

        case 'control':
            if (result.operation === 'listen') {
                await openSSE(req, res, deps, result.sessionId)
                return
            }
            if (result.operation === 'cancel') {
                // Publish a cancel on the session's input channel — the runner
                // subscribes for the lifetime of the run and aborts the agent
                // loop when it arrives.
                try {
                    await deps.bus.publishInput(result.sessionId, {
                        type: 'cancel',
                        at: new Date().toISOString(),
                    })
                    res.status(202).json({ ok: true })
                } catch (err) {
                    logger.error('cancel failed', { sessionId: result.sessionId, error: String(err) })
                    res.status(503).json({ error: 'cancel failed' })
                }
                return
            }
            // operation === 'send'
            try {
                await deps.bus.publishInput(result.sessionId, {
                    type: 'user_message',
                    at: new Date().toISOString(),
                    content: result.payload?.content ?? '',
                })
                res.status(202).json({ ok: true })
            } catch (err) {
                logger.error('send failed', { sessionId: result.sessionId, error: String(err) })
                res.status(503).json({ error: 'send failed' })
            }
            return
    }
}

async function openSSE(req: Request, res: Response, deps: ServerDeps, sessionId: string): Promise<void> {
    res.setHeader('content-type', 'text/event-stream')
    res.setHeader('cache-control', 'no-cache')
    res.setHeader('connection', 'keep-alive')
    res.flushHeaders?.()
    res.write('retry: 5000\n\n')

    const send = (event: SessionEvent): void => {
        res.write(`event: ${event.type}\n`)
        res.write(`data: ${JSON.stringify(event)}\n\n`)
    }

    const unsubscribe = await deps.bus.subscribeEvents(sessionId, send)
    const heartbeat = setInterval(() => res.write(': heartbeat\n\n'), 15_000)
    const cleanup = async (): Promise<void> => {
        clearInterval(heartbeat)
        try {
            await unsubscribe()
        } catch (err) {
            logger.error('listen cleanup error', { sessionId, error: String(err) })
        }
    }
    req.on('close', () => void cleanup())
}
