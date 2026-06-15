/**
 * Trigger module interface.
 *
 * Each trigger ships exactly one module — a list of self-describing routes.
 * Every route declares the auth it requires *and* the handler that runs, in
 * the same object. The ingress mounts each route through a guard derived from
 * that `auth` field (see `mount.ts`) and publishes the same field via
 * `GET /agents/<slug>/schemas`. Declared auth and enforced auth are therefore
 * the same data — a route cannot advertise `agent_spec` while its handler
 * forgets to authenticate, which is the class of bug that previously left
 * `/listen` and `/mcp/stream` open.
 *
 * Adding a new trigger:
 *
 *   1. Write `triggers/<name>.ts` exporting a `TriggerModule`.
 *   2. Add the module to `TRIGGER_MODULES` in `routing/server.ts`.
 *   3. Done — guards, schemas, and auth advertisement all cascade from `routes`.
 */

import type { Request, Response } from 'express'
import type { Pool } from 'pg'

import type {
    AuthConfig,
    CredentialBroker,
    CredentialMap,
    HttpFetcher,
    IdentityStore,
    IntegrationStore,
    SecretResolver,
    SessionEventBus,
    SessionPrincipal,
    SessionQueue,
    Trigger,
} from '@posthog/agent-shared'

import type { AuthProvider, VerifyResult } from '../enqueue/auth'
import type { ResolvedAgent, RevisionResolver, RoutingMode } from '../routing/resolver'

/** Superset of every dep any trigger handler needs. Handlers pick what they use. */
export interface TriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    bus: SessionEventBus
    authProvider?: AuthProvider
    /** Resolves the per-agent Slack signing secret named by `slack.config.signing_secret_ref`. */
    signingSecretResolver: SecretResolver
    identities?: IdentityStore
    /**
     * Per-session credential broker. Chat trigger consumes it on /run + /send;
     * other triggers ignore it. Required — prod wires `PgCredentialBroker`,
     * tests wire the same against the test DB.
     */
    broker: CredentialBroker
    /**
     * Read-only access to PostHog's integration table. Slack trigger uses it
     * to fetch a workspace bot token for the Slack → PostHog user bridge.
     * Optional — when absent, the bridge is skipped.
     */
    integrations?: IntegrationStore | null
    /** Direct posthog DB pool for the Slack → PostHog user bridge's email lookup. */
    posthogDb?: Pool | null
    /**
     * Outbound HTTP — currently only the slack trigger consumes it (for
     * the identity bridge's Slack `users.info` call). Wired at the
     * ingress entrypoint so the call dispatches through smokescreen in
     * prod alongside every other fetch.
     */
    http?: HttpFetcher
    /** Routing mode + URL inputs the MCP connect-info endpoint advertises. */
    routingMode?: RoutingMode
    domainSuffix?: string
    publicBaseUrl?: string
}

/** Pulled from the `Trigger` discriminator in `@posthog/agent-shared` so this
 *  list can't drift from the spec schema. */
export type TriggerType = Trigger['type']

/**
 * How a route is authenticated. Drives both the guard the route is mounted
 * behind (`mount.ts`) and the shape `/schemas` publishes per agent.
 *
 * - `agent_spec` — the agent's `spec.auth` block. The guard runs `authorize`
 *   and the handler receives an `AuthedRouteCtx` with a guaranteed principal.
 * - `custom` — the agent is resolved and `authConfig` is provided, but the
 *   guard does NOT authorize; the handler calls `ctx.authorize()` itself.
 *   For routes that multiplex several logical operations with different auth
 *   over one HTTP endpoint (MCP's JSON-RPC `/mcp`, where `initialize` is
 *   pre-auth).
 * - `slack_signing` — Slack signature verification on the request body.
 * - `public` — no auth (discovery / healthz-style routes).
 */
export type RouteAuthKind = 'agent_spec' | 'custom' | 'slack_signing' | 'public'

/** Context every route handler receives. The agent is always resolved. */
export interface RouteCtx {
    req: Request
    res: Response
    deps: TriggerDeps
    resolved: ResolvedAgent
}

/** `agent_spec` routes: the guard authenticated the caller before the handler ran. */
export interface AuthedRouteCtx extends RouteCtx {
    authConfig: AuthConfig
    principal: SessionPrincipal
    credentials: CredentialMap
}

/** `custom` routes: agent + authConfig resolved; the handler authorizes on demand. */
export interface CustomAuthRouteCtx extends RouteCtx {
    authConfig: AuthConfig
    /** Run the agent's auth gate (per JSON-RPC method, etc.). */
    authorize(): Promise<VerifyResult>
}

interface RouteCommon {
    method: 'GET' | 'POST'
    /** Path relative to the agent mount (e.g. `/run`, `/slack/events`). */
    path: string
    /** JSON Schema for the request body. POST routes only. Omit when the
     *  trigger genuinely accepts arbitrary payloads (e.g. webhook). */
    bodySchema?: object
    /** JSON Schema for the query string. GET routes that read params. */
    querySchema?: object
}

/**
 * A route + its auth + its handler, in one object. The `auth` discriminant
 * fixes the context the handler receives, so the type system enforces that an
 * `agent_spec` route reads `ctx.principal` (guaranteed) while a `public` route
 * cannot.
 */
export type TriggerRoute =
    | (RouteCommon & { auth: 'agent_spec'; handler: (ctx: AuthedRouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'custom'; handler: (ctx: CustomAuthRouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'slack_signing'; handler: (ctx: RouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'public'; handler: (ctx: RouteCtx) => Promise<void> })

export interface TriggerModule {
    type: TriggerType
    /** Routes this trigger owns — drives mounting, guards, and `/schemas`. */
    routes: TriggerRoute[]
}
