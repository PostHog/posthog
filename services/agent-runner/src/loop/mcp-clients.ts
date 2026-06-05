/**
 * Open MCP clients for an agent's `spec.mcps[]` at session start. Each opened
 * client carries:
 *   - `prefix` — the model-visible name prefix (`<prefix>__<remoteToolName>`).
 *   - `listTools()` — list of remote tools (used by `buildAgentTools` to emit
 *     one `AgentTool` per remote tool).
 *   - `callTool(name, args)` — invoke; result is the raw MCP `CallToolResult`.
 *     `buildAgentTools` owns the translation into `AgentToolResult`.
 *   - `close()` — best-effort transport shutdown.
 *
 * Auth resolution — see `docs/agent-platform/plans/runtime-mcps.md`:
 *   - `auth.integration` → `integrations[ref].access_token` →
 *     `Authorization: Bearer <token>`.
 *   - `secrets[]` → resolve each name via `secrets[NAME]`; substitute
 *     `${NAME}` placeholders in the URL before opening the transport.
 *
 * Failure during open: any single ref's open is wrapped in `Promise.allSettled`
 * so a partial-open doesn't leak clients. The first error is re-thrown after
 * the already-opened clients are closed — matching sandbox-acquire's
 * all-or-nothing contract. The caller (worker) marks the session failed.
 *
 * NOT in scope for this module: tool-name prefixing (the caller composes
 * `${prefix}__${toolName}`), inclusion filtering via `ref.tools[]` (the
 * caller iterates `listTools()` and skips entries not in the names projected
 * from `ref.tools`), or the per-tool approval wrap (driver looks the policy
 * up via `mcp-tool-lookup.ts`). Keeping those concerns in `buildAgentTools`
 * + `driver` matches how native/custom tools already work.
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'

import { HttpFetcher, IntegrationCredentials, McpRef } from '@posthog/agent-shared'

/** Remote tool descriptor as returned by `client.listTools()`. */
export interface RemoteMcpTool {
    name: string
    description: string
    /**
     * JSON Schema fragment. `buildAgentTools` (PR 3) casts this to pi-ai's
     * `TSchema` — same as the existing `kind: 'client'` tool path does for
     * author-supplied schemas. The SDK guarantees a `{ type: 'object', ... }`
     * shape per the MCP protocol.
     */
    inputSchema: unknown
}

/** Raw MCP `CallToolResult` — `buildAgentTools` shapes this into an
 *  `AgentToolResult` and decides how to surface `isError` to the model. */
export type McpCallResult = Awaited<ReturnType<Client['callTool']>>

export interface OpenedMcp {
    /** Tool-name prefix at runtime: `<prefix>__<remoteToolName>`. */
    prefix: string
    /** The original spec ref this client was opened for. Handy for logging
     *  and for the caller to inspect `tools[]` per tool. */
    ref: McpRef
    listTools(): Promise<RemoteMcpTool[]>
    callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult>
    close(): Promise<void>
}

/**
 * Factory for the underlying SDK transport. Defaults to
 * `StreamableHTTPClientTransport`. Tests override with a factory that pairs
 * with an in-process `McpServer` via `InMemoryTransport.createLinkedPair()`.
 */
export type McpTransportFactory = (target: { url: string; headers: Record<string, string> }) => Transport

/**
 * Per-call validator the runner consults before stamping a connected
 * integration's bearer token on an outbound MCP request. Returns `true` to
 * allow attachment, `false` to reject. The worker is expected to wire a
 * validator that maps the integration kind (e.g. `linear`, `github`) to
 * the host pattern that integration is authorised for; without a wired
 * validator, every `auth.integration`-bearing ref is **refused at open
 * time** so a malicious spec author can't redirect a team's OAuth token
 * to an arbitrary URL.
 *
 * See `docs/agent-platform/plans/runtime-mcps.md` "Auth resolution" and
 * the PR-6 security thread for the threat model.
 */
export type IntegrationHostValidator = (integrationRef: string, url: URL) => boolean

export interface OpenMcpClientsDeps {
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets keyed by name (same shape `runSession`
     *  already threads through). Only the names listed on a given ref's
     *  `secrets[]` are substituted into that ref's URL. */
    secrets: Record<string, string>
    transportFactory?: McpTransportFactory
    log?: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
    /** Identity sent during the MCP `initialize` handshake. Defaults to the
     *  runner's own name + a static version stamp. */
    clientInfo?: { name: string; version: string }
    /**
     * Validator that decides whether a connected integration's bearer token
     * may be attached to a given MCP URL. Fail-closed: when unset, any
     * `auth.integration`-bearing external ref is refused at open time
     * (`mcp_integration_host_validator_not_wired`). See the type definition
     * for the threat model.
     */
    integrationHostValidator?: IntegrationHostValidator
    /**
     * Dev-only bearer attached to `kind: external` MCP requests when the
     * ref has no `auth.integration` of its own (`ref.auth` wins if set).
     * Bridges the local-dev auth gap until external-MCP credentials are
     * sourced from the per-session credential broker. Production refuses
     * to set this at boot.
     */
    devMcpBearerToken?: string
    /**
     * Outbound HTTP client. Passed as the SDK transport's `fetch` option so
     * MCP traffic dispatches through the same proxy as native tools (in
     * prod that's smokescreen). When omitted, the SDK uses its built-in
     * global `fetch` — fine for tests, never set in prod.
     */
    http?: HttpFetcher
}

const DEFAULT_CLIENT_INFO = { name: 'posthog-agent-runner', version: '0.1.0' }

const noopLog: NonNullable<OpenMcpClientsDeps['log']> = () => {}

function makeDefaultTransportFactory(http?: HttpFetcher): McpTransportFactory {
    // Bind ahead of time so each transport call dispatches through the same
    // HttpClient — undefined falls back to the SDK's built-in global fetch.
    const boundFetch = http ? http.fetch.bind(http) : undefined
    return ({ url, headers }) =>
        new StreamableHTTPClientTransport(new URL(url), {
            requestInit: { headers },
            ...(boundFetch ? { fetch: boundFetch } : {}),
        })
}

/**
 * Open one MCP client per entry in `refs`, returning a stable list plus a
 * batched `close()` callable from the worker's `finally`. See module header
 * for failure semantics + auth resolution.
 */
export async function openMcpClients(
    refs: readonly McpRef[],
    deps: OpenMcpClientsDeps
): Promise<{ clients: OpenedMcp[]; close: () => Promise<void> }> {
    if (refs.length === 0) {
        return { clients: [], close: async () => {} }
    }

    const log = deps.log ?? noopLog
    const transportFactory = deps.transportFactory ?? makeDefaultTransportFactory(deps.http)
    const clientInfo = deps.clientInfo ?? DEFAULT_CLIENT_INFO

    // Parallel open — N refs would otherwise stack N round-trips at session
    // start. `allSettled` so a partial-open doesn't leak the successful clients.
    const results = await Promise.allSettled(
        refs.map((ref) => openOne(ref, { ...deps, transportFactory, clientInfo, log }))
    )

    const opened: OpenedMcp[] = []
    let firstErr: Error | undefined
    for (const r of results) {
        if (r.status === 'fulfilled') {
            opened.push(r.value)
        } else if (!firstErr) {
            firstErr = r.reason instanceof Error ? r.reason : new Error(String(r.reason))
        }
    }
    if (firstErr) {
        await closeAll(opened, log)
        throw firstErr
    }

    // Duplicate prefix = the model would see two tools with the same fully
    // qualified name. Surface this loud at open time rather than letting one
    // silently shadow the other downstream.
    const prefixes = new Set<string>()
    for (const o of opened) {
        if (prefixes.has(o.prefix)) {
            await closeAll(opened, log)
            throw new Error(`duplicate_mcp_prefix: ${o.prefix}`)
        }
        prefixes.add(o.prefix)
    }

    return {
        clients: opened,
        close: async () => closeAll(opened, log),
    }
}

interface OpenOneDeps extends OpenMcpClientsDeps {
    transportFactory: McpTransportFactory
    clientInfo: { name: string; version: string }
    log: NonNullable<OpenMcpClientsDeps['log']>
}

async function openOne(ref: McpRef, deps: OpenOneDeps): Promise<OpenedMcp> {
    const target = await resolveTarget(ref, deps)
    const transport = deps.transportFactory(target)
    const client = new Client(deps.clientInfo, { capabilities: {} })
    await client.connect(transport)

    const prefix = ref.id
    return {
        prefix,
        ref,
        listTools: async () => {
            const res = await client.listTools()
            return res.tools.map((t) => ({
                name: t.name,
                description: t.description ?? '',
                inputSchema: t.inputSchema,
            }))
        },
        callTool: async (name, args) => client.callTool({ name, arguments: args }),
        close: async () => {
            try {
                await client.close()
            } catch (err) {
                deps.log('warn', 'mcp.close.failed', { prefix, err: (err as Error).message })
            }
        },
    }
}

async function resolveTarget(
    ref: McpRef,
    deps: OpenMcpClientsDeps
): Promise<{ url: string; headers: Record<string, string> }> {
    // SSRF protection is handled at the infra layer by smokescreen (see
    // charts/shared/agent-platform/common.yaml `httpProxy.enabled: true`).
    // Author chose the URL; smokescreen denies RFC1918 / loopback /
    // link-local / cloud-IMDS + closes the DNS-rebinding gap via per-IP
    // resolution at connect time. The runner only handles the logical-binding
    // check (integration → host allowlist), which smokescreen can't do.
    const url = substituteSecrets(ref.url, ref.secrets, deps.secrets)
    const headers: Record<string, string> = {}
    if (ref.auth?.integration) {
        const cred = deps.integrations[ref.auth.integration]
        if (!cred) {
            throw new Error(`mcp_integration_not_resolved: ${ref.auth.integration}`)
        }
        // Fail-closed integration host binding: an author can't redirect a
        // team's OAuth token to an arbitrary URL because the worker's
        // validator gates which host each integration kind is allowed to
        // talk to. The unwired-validator branch refuses unconditionally so
        // a config-drift / deploy issue can't silently regress to "attach
        // bearer to anything." See `IntegrationHostValidator` doc + the
        // PR-6 security thread.
        if (!deps.integrationHostValidator) {
            throw new Error(`mcp_integration_host_validator_not_wired: ${ref.auth.integration}`)
        }
        const parsed = new URL(url)
        // Smokescreen owns SSRF, but it can't guarantee the OAuth bearer isn't
        // sent in cleartext to an allowlisted public host — it filters by
        // destination, not scheme. The host validator below only checks
        // `url.host`, so without this an author could set `http://api.slack.com`
        // and have the team's token stamped onto a plaintext request. Enforce
        // https on the credential path only; non-auth external URLs stay
        // smokescreen's concern.
        if (parsed.protocol !== 'https:') {
            throw new Error(`mcp_integration_unsafe_scheme: ${ref.auth.integration} → ${parsed.protocol}`)
        }
        if (!deps.integrationHostValidator(ref.auth.integration, parsed)) {
            throw new Error(`mcp_integration_host_not_allowed: ${ref.auth.integration} → ${parsed.host}`)
        }
        headers['Authorization'] = `Bearer ${cred.access_token}`
    } else if (deps.devMcpBearerToken) {
        // Dev-only fallback. The bundle declared no integration auth, but
        // the operator wired a global dev bearer (their PAT, typically) so
        // the local MCP server accepts the call. `ref.auth` always wins
        // when set; this branch only fires when the spec is auth-less.
        headers['Authorization'] = `Bearer ${deps.devMcpBearerToken}`
    }
    // Author-supplied headers — the BYO-bearer-token path. Walked after the
    // integration / dev-bearer blocks so explicit author entries take
    // precedence on duplicate keys (matches `http-request`'s "caller-set
    // values are not silently overwritten" rule). Substituted from the
    // ref's `secrets[]` declarations — missing-secret throws the same
    // mcp_secret_not_resolved error as the URL path.
    if (ref.headers) {
        for (const [name, raw] of Object.entries(ref.headers)) {
            headers[name] = substituteSecrets(raw, ref.secrets, deps.secrets)
        }
    }
    return { url, headers }
}

/**
 * Substitute `${NAME}` placeholders in `input` for each name listed on the
 * ref's `secrets[]`. Missing names throw at open time rather than passing a
 * literal `${NAME}` to the remote server — the latter would silently fail at
 * the protocol layer with no useful error.
 */
function substituteSecrets(input: string, declared: readonly string[], available: Record<string, string>): string {
    let out = input
    for (const name of declared) {
        const value = available[name]
        if (value === undefined) {
            throw new Error(`mcp_secret_not_resolved: ${name}`)
        }
        out = out.split(`\${${name}}`).join(value)
    }
    return out
}

async function closeAll(opened: readonly OpenedMcp[], log: NonNullable<OpenMcpClientsDeps['log']>): Promise<void> {
    const results = await Promise.allSettled(opened.map((o) => o.close()))
    for (let i = 0; i < results.length; i++) {
        const r = results[i]
        if (r.status === 'rejected') {
            log('warn', 'mcp.close.batch_failed', {
                prefix: opened[i].prefix,
                err: r.reason instanceof Error ? r.reason.message : String(r.reason),
            })
        }
    }
}
