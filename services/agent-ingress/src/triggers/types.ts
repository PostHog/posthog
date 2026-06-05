/**
 * Trigger module interface.
 *
 * Each trigger ships exactly one module — a router plus a self-description of
 * the HTTP routes it owns. The ingress assembles modules at boot:
 *
 *   1. Mount every module's router under the agent slug.
 *   2. Read every module's `routes` to publish the agent's API surface via
 *      `GET /agents/<slug>/schemas`.
 *
 * That single registration is the only place a new trigger needs to plug in —
 * `/schemas`, router mounting, and (eventually) docs all cascade from it. No
 * hand-maintained map of "which trigger types are published" to keep in sync.
 *
 * Adding a new trigger:
 *
 *   1. Write `triggers/<name>.ts` exporting a `TriggerModule`.
 *   2. Add the new module to `TRIGGER_MODULES` in `routing/server.ts`.
 *   3. Done — schemas, mounting, and auth advertisement come for free.
 */

import { Router } from 'express'

import type { IdentityStore, SessionEventBus, SessionQueue, Trigger } from '@posthog/agent-shared'

import type { AuthProvider } from '../enqueue/auth'
import type { RevisionResolver } from '../routing/resolver'
import type { SlackSigningSecretResolver } from './slack'

/** Superset of every dep any trigger router needs. Triggers pick what they use. */
export interface TriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    bus: SessionEventBus
    teamId: number
    authProvider?: AuthProvider
    /** Resolves the per-agent Slack signing secret named by `slack.config.signing_secret_ref`. */
    signingSecretResolver: SlackSigningSecretResolver
    identities?: IdentityStore
}

/** Pulled from the `Trigger` discriminator in `@posthog/agent-shared` so this
 *  list can't drift from the spec schema. */
export type TriggerType = Trigger['type']

/**
 * How a route is authenticated. Resolved against the agent's `spec.auth` at
 * `/schemas` render-time so the response tells callers exactly what creds to
 * bring per agent — not just per trigger type.
 *
 * - `agent_spec` — uses the agent's `spec.auth` block (public / pat /
 *   posthog_internal / shared_secret + optional header name).
 * - `slack_signing` — Slack signature verification on the request body.
 * - `public` — no auth (healthz-style or fully open routes).
 */
export type RouteAuthKind = 'agent_spec' | 'slack_signing' | 'public'

export interface TriggerRoute {
    method: 'GET' | 'POST'
    /** Path relative to the agent mount (e.g. `/run`, `/slack/events`). */
    path: string
    /** JSON Schema for the request body. POST routes only. Omit when the
     *  trigger genuinely accepts arbitrary payloads (e.g. webhook) — callers
     *  read this as "we don't enforce a shape here." */
    bodySchema?: object
    /** JSON Schema for the query string. GET routes that read params. */
    querySchema?: object
    /** What's required to call this route. Rendered concretely per-agent. */
    auth: RouteAuthKind
}

export interface TriggerModule {
    type: TriggerType
    /** Express router for this trigger, factory-style so deps are runtime. */
    router: (deps: TriggerDeps) => Router
    /** Routes this trigger publishes. Drives `/schemas` directly. */
    routes: TriggerRoute[]
}
