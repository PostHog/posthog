/**
 * Run PostHog's own MCP tools against a *different* PostHog project, over a `posthog` connection.
 *
 * A connection (`posthog/api/posthog_connection.py`) holds a user-consented OAuth grant on another
 * project, in another region or the same one, and exposes a single `forward/` endpoint that replays
 * an arbitrary API request there with the stored token injected. The token never reaches this
 * service.
 *
 * Every tool in this codebase is, underneath, a shaped call to the PostHog API — so pointing a tool
 * at another project needs nothing more than an `ApiClient` whose requests come out the other end of
 * that endpoint. `ApiClient` funnels all of its traffic through one `fetch` seam, so a subclass that
 * overrides it re-routes the whole surface at once: `request`, the endpoint helpers, and anything
 * built on them. That is the translation layer this module provides, and the reason an agent can
 * call `execute-sql` on a connected EU project rather than hand-assembling
 * `POST api/projects/<id>/query/` and a HogQL envelope.
 */

import { ApiClient } from '@/api/client'
import type { Schemas } from '@/api/generated'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { PostHogApiError } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'
import type { Context, State } from '@/tools/types'

/** Shape the `forward/` endpoint answers with: the target's own status, and its body verbatim. */
interface ForwardResponse {
    status: number
    data: unknown
}

/** What `target/` reports about the far end of a connection. */
export type ConnectionTarget = Schemas.PostHogConnectionTarget

export interface ForwardingOptions {
    /** Integration id of the `posthog` connection to route through. */
    connectionId: string
    /** Project id on *this* side — the one that owns the connection and the `forward/` endpoint. */
    localProjectId: string
    target: ConnectionTarget
}

/**
 * Stands in for the caller's token on a forwarded client, which has no use for one: `forward/`
 * injects the connection's own token inside Django. Anything that reaches the network by reading
 * `config.apiToken` instead of going through `fetch` therefore sends this and gets a 401, rather
 * than putting the caller's bearer token on the wire to another account's project.
 */
export const FORWARDED_API_TOKEN = 'posthog-connection-forwarded'

/**
 * An `ApiClient` whose every call is replayed against the connected project.
 *
 * `baseUrl` is the target's, so paths and rendered `_posthogUrl` links read as the other project's,
 * but no request is ever sent there directly: `fetch` unpicks the URL it was handed back into the
 * `{method, path, query, data}` shape `forward/` takes and posts that to the local API instead.
 */
export class ForwardingApiClient extends ApiClient {
    private readonly local: ApiClient
    private readonly options: ForwardingOptions

    constructor(local: ApiClient, options: ForwardingOptions) {
        super({
            ...local.config,
            apiToken: FORWARDED_API_TOKEN,
            baseUrl: options.target.base_url,
            publicBaseUrl: options.target.base_url,
        })
        this.local = local
        this.options = options
    }

    protected override async fetch(url: string, init?: RequestInit): Promise<Response> {
        const parsed = new URL(url)
        const query: Record<string, string> = {}
        for (const [key, value] of parsed.searchParams.entries()) {
            query[key] = value
        }

        const body: Record<string, unknown> = {
            method: (init?.method ?? 'GET').toUpperCase(),
            path: parsed.pathname.replace(/^\/+/, ''),
        }
        if (Object.keys(query).length > 0) {
            body['query'] = query
        }
        const payload = parseJsonBody(init?.body)
        if (payload !== undefined) {
            body['data'] = payload
        }

        let forwarded: ForwardResponse
        try {
            forwarded = await this.local.request<ForwardResponse>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(this.options.localProjectId)}/posthog_connections/${encodeURIComponent(this.options.connectionId)}/forward/`,
                body,
            })
        } catch (error) {
            // A refusal on *this* side — connection gone, caller's scopes too narrow, target
            // unreachable — is the answer to the request the tool made, so hand it back as that
            // request's response rather than as an exception the tool has no shape for.
            if (error instanceof PostHogApiError) {
                return jsonResponse(error.status, safeParse(error.body))
            }
            throw error
        }

        return jsonResponse(forwarded.status, forwarded.data)
    }
}

function jsonResponse(status: number, data: unknown): Response {
    return new Response(JSON.stringify(data ?? null), {
        status,
        headers: { 'Content-Type': 'application/json' },
    })
}

function safeParse(body: unknown): unknown {
    if (typeof body !== 'string') {
        return body ?? null
    }
    try {
        return JSON.parse(body)
    } catch {
        return { detail: body }
    }
}

/** Recover the object a caller passed as `body`. Non-JSON bodies (none are sent today) are dropped
 *  rather than forwarded as a string the endpoint would reject. */
function parseJsonBody(body: BodyInit | null | undefined): unknown {
    if (typeof body !== 'string' || body.length === 0) {
        return undefined
    }
    try {
        return JSON.parse(body)
    } catch {
        return undefined
    }
}

/**
 * Ask the connection where it points. Cached server-side, so repeated calls in a session cost one
 * local request and no cross-region hop.
 */
export async function resolveConnectionTarget(
    context: Context,
    localProjectId: string,
    connectionId: string
): Promise<ConnectionTarget> {
    return await context.api.request<ConnectionTarget>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(localProjectId)}/posthog_connections/${encodeURIComponent(connectionId)}/target/`,
    })
}

/**
 * A `Context` that resolves to the connected project instead of this one.
 *
 * The state manager is a fresh instance over its own cache, seeded with the target's ids, for two
 * reasons: tools read the project and org id from it to build their paths, and anything it fetches
 * lazily (the user, group types, the project record) must not land in the session cache that this
 * project's own tools read back.
 */
export function buildForwardedContext(context: Context, options: ForwardingOptions): Context {
    const api = new ForwardingApiClient(context.api, options)
    // `MemoryCache` scopes are process-global, so the key carries both ids. Only a connection's
    // creator can use it, so this can never be shared across users — the local project id just keeps
    // that true without depending on the backend check to hold it up.
    const cache = new MemoryCache<State>(`posthog-connection:${options.localProjectId}:${options.connectionId}`)
    const stateManager = new StateManager(cache, api)

    return {
        ...context,
        api,
        cache,
        stateManager,
        connection: { localProjectId: options.localProjectId, connectionId: options.connectionId },
    }
}

/** Seed the forwarded cache so no tool has to resolve the target's default project itself. */
export async function seedForwardedContext(forwarded: Context, target: ConnectionTarget): Promise<void> {
    await forwarded.cache.setMany({
        projectId: String(target.project_id),
        orgId: target.organization_id,
    })
}
