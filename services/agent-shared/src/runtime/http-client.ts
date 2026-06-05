/**
 * Single-class HTTP client for every outbound fetch in the agent platform.
 *
 * Wraps `undici.fetch` with two policies:
 *   - **Proxy dispatcher** — when `proxyUrl` is set, all requests route
 *     through an `undici.ProxyAgent`. In prod that's smokescreen (SSRF
 *     enforcement); in dev/test it's unset and requests go direct.
 *     Node's built-in `fetch` does **not** read `HTTP_PROXY` / `HTTPS_PROXY`
 *     env vars on its own, so bare `fetch(...)` calls would silently
 *     bypass smokescreen — that's why every outbound call in the agent
 *     services must go through this client.
 *   - **Default timeout** — applied via `AbortSignal.timeout` when the
 *     caller doesn't supply their own signal. A long-running provider
 *     call without a timeout will otherwise hang the worker forever.
 *
 * Tests and the harness construct this directly with no proxy URL; unit
 * tests of individual tools substitute `ctx.http` with a `vi.fn()` mock
 * at the seam (the structural `HttpFetcher` type below makes that a
 * one-liner — no separate fake class).
 */

import { ProxyAgent, fetch as undiciFetch, type Dispatcher } from 'undici'

/** Structural type for `ToolContext.http` — anything with a fetch method. */
export interface HttpFetcher {
    fetch: (input: string | URL, init?: RequestInit) => Promise<Response>
}

export interface HttpClientOptions {
    /**
     * Proxy URL. In prod, set to the smokescreen URL (see
     * `charts/shared/agent-platform/common.yaml` `httpProxy.enabled`).
     * Unset in dev / harness — requests go direct.
     */
    proxyUrl?: string
    /** Per-request timeout when the caller didn't supply a signal. Default 30s. */
    defaultTimeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 30_000

export class HttpClient implements HttpFetcher {
    private readonly dispatcher: Dispatcher | undefined
    private readonly defaultTimeoutMs: number

    constructor(opts: HttpClientOptions = {}) {
        this.dispatcher = opts.proxyUrl ? new ProxyAgent(opts.proxyUrl) : undefined
        this.defaultTimeoutMs = opts.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS
    }

    async fetch(input: string | URL, init?: RequestInit): Promise<Response> {
        const signal = init?.signal ?? AbortSignal.timeout(this.defaultTimeoutMs)
        // undici's RequestInit accepts a `dispatcher` field that the global
        // fetch types don't expose; the merged object only conforms to
        // undici's shape, hence the `unknown` step. The runtime fetch is
        // still undici under the hood, so the call is correct.
        const merged = { ...init, signal, dispatcher: this.dispatcher } as unknown as Parameters<typeof undiciFetch>[1]
        return undiciFetch(input, merged) as unknown as Response
    }
}
