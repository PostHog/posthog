/**
 * Open MCP clients for an agent's `spec.mcps[]` at session start. Each opened
 * client carries:
 *   - `prefix` — the model-visible name prefix (`<prefix>__<remoteToolName>`).
 *   - `listTools()` — list of remote tools (used by `buildAgentTools` in PR 3
 *     to emit one `AgentTool` per remote tool).
 *   - `callTool(name, args)` — invoke; result is the raw MCP `CallToolResult`.
 *     PR 3 owns the translation into `AgentToolResult`; here we surface the
 *     SDK result as-is so the caller can inspect `isError`/`content` itself.
 *   - `close()` — best-effort transport shutdown.
 *
 * Auth resolution per variant — see `docs/agent-platform/plans/runtime-mcps.md`
 * "Auth resolution":
 *   - `external.auth.integration` → `integrations[ref].access_token` →
 *     `Authorization: Bearer <token>`.
 *   - `external.secrets[]` → resolve each name via `secrets[NAME]`; substitute
 *     `${NAME}` placeholders in the URL before opening the transport.
 *   - `kind: 'agent'` → defers to `deps.agentMcpResolver(slug)`. The resolver
 *     is wired in PR 6 (it walks the local revision store + mints
 *     `posthog_internal` auth); when unset, opening an `agent` ref throws
 *     `agent_mcp_resolver_not_wired` so the failure is visible during the
 *     PR 2-5 staging window rather than silently degrading.
 *
 * Failure during open: any single ref's open is wrapped in `Promise.allSettled`
 * so a partial-open doesn't leak clients. The first error is re-thrown after
 * the already-opened clients are closed — matching sandbox-acquire's
 * all-or-nothing contract. The caller (worker) marks the session failed.
 *
 * NOT in scope for this module: tool-name prefixing (the caller composes
 * `${prefix}__${toolName}`), allowlist filtering (the caller iterates
 * `listTools()` and skips entries not in `ref.allowlist`). Keeping those
 * concerns in `buildAgentTools` matches how native/custom tools already work.
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'

import { IntegrationCredentials, McpRef } from '@posthog/agent-shared'

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
     *  and for the caller to inspect `allowlist` / `kind` per tool. */
    ref: McpRef
    listTools(): Promise<RemoteMcpTool[]>
    callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult>
    close(): Promise<void>
}

/**
 * Caller context passed to `AgentMcpResolver`. Production resolvers need this
 * to enforce team isolation — slug alone is ambiguous across teams, and the
 * "agent A in team 1 reaches into agent B in team 2 because they share a
 * slug" hole would otherwise be open by default.
 */
export interface AgentMcpResolverContext {
    teamId: number
    sessionId: string
}

/**
 * Resolves a `kind: 'agent'` ref into a transport target. Production wires a
 * default that looks up the target by `(teamId, slug)` in the local revision
 * store, builds the ingress URL (`/agents/<slug>/mcp` in path mode,
 * `<slug>.agents.posthog.com/mcp` in domain mode), and mints a
 * `posthog_internal` bearer. Tests inject a synthetic resolver that just
 * fabricates a URL — see `cases/mcp-tools.test.ts`. When unset, opening an
 * `agent` ref throws `agent_mcp_resolver_not_wired` so the gap is loud
 * rather than silent.
 */
export type AgentMcpResolver = (
    slug: string,
    ctx: AgentMcpResolverContext
) => Promise<{ url: string; headers: Record<string, string> }>

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
    /**
     * Forwarded to `agentMcpResolver` for every `kind: 'agent'` ref. Required
     * iff at least one ref is `kind: 'agent'` — `external` refs ignore it.
     * The caller (worker) populates this from the session being run.
     */
    callerContext?: AgentMcpResolverContext
    agentMcpResolver?: AgentMcpResolver
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
}

const DEFAULT_CLIENT_INFO = { name: 'posthog-agent-runner', version: '0.1.0' }

const noopLog: NonNullable<OpenMcpClientsDeps['log']> = () => {}

const defaultTransportFactory: McpTransportFactory = ({ url, headers }) =>
    new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers } })

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
    const transportFactory = deps.transportFactory ?? defaultTransportFactory
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

    const prefix = ref.kind === 'agent' ? ref.slug : ref.id
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
    if (ref.kind === 'agent') {
        if (!deps.agentMcpResolver) {
            throw new Error('agent_mcp_resolver_not_wired')
        }
        if (!deps.callerContext) {
            // The resolver needs `(teamId, sessionId)` to enforce isolation; a
            // missing context here means the worker forgot to forward session
            // info. Surface loudly rather than letting the resolver decide what
            // to do with `undefined`.
            throw new Error('agent_mcp_caller_context_missing')
        }
        return deps.agentMcpResolver(ref.slug, deps.callerContext)
    }
    // `external` variant.
    const url = substituteSecrets(ref.url, ref.secrets, deps.secrets)
    assertSafeExternalMcpUrl(url)
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
        if (!deps.integrationHostValidator(ref.auth.integration, parsed)) {
            throw new Error(`mcp_integration_host_not_allowed: ${ref.auth.integration} → ${parsed.host}`)
        }
        headers['Authorization'] = `Bearer ${cred.access_token}`
    }
    return { url, headers }
}

/**
 * SSRF floor for `kind: 'external'` MCP URLs. The author-supplied URL passes
 * Zod's `.url()` validator (a syntactic check) and could otherwise resolve
 * to private / loopback / cloud-metadata addresses. This rejects the
 * obvious cases at open time:
 *
 *   - non-HTTPS schemes (no plaintext, no `ws://`, no `file://`)
 *   - IPv4 loopback / RFC1918 / link-local / cloud-metadata literals
 *   - IPv6 loopback / link-local / unique-local
 *   - hostnames ending in `.local` or `.internal` (mDNS / private DNS)
 *
 * This is a best-effort string-pattern check, NOT DNS-time validation —
 * a hostname like `evil.com` that A-records to `127.0.0.1` slips through.
 * Closing that gap requires a custom HTTP agent that resolves DNS and
 * inspects the resolved IP before connect; tracked as a follow-up in the
 * plan. The string check still raises the floor enough to address the
 * concrete attacks called out in the PR-6 security review:
 *   - `https://169.254.169.254/...` (AWS / Azure IMDS)
 *   - `https://10.0.0.1/...` (private LAN)
 *   - `http://...` (downgrade to plaintext for credential capture)
 *
 * `kind: 'agent'` URLs are minted by the resolver — not author input —
 * so they don't pass through here.
 */
export function assertSafeExternalMcpUrl(url: string): void {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        throw new Error(`mcp_unsafe_url: not a valid URL`)
    }
    if (parsed.protocol !== 'https:') {
        throw new Error(`mcp_unsafe_url: scheme must be https (got '${parsed.protocol}')`)
    }
    if (isUnsafeMcpHost(parsed.hostname)) {
        throw new Error(`mcp_unsafe_url: hostname '${parsed.hostname}' is private / loopback / link-local`)
    }
}

const UNSAFE_HOST_PATTERNS: ReadonlyArray<RegExp> = [
    /^localhost$/i,
    /^localhost\./i,
    // IPv4 loopback / link-local / RFC1918 / first-octet 0.x / cloud-IMDS.
    /^0\.\d{1,3}\.\d{1,3}\.\d{1,3}$/,
    /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/,
    /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/,
    /^192\.168\.\d{1,3}\.\d{1,3}$/,
    /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/,
    /^169\.254\.\d{1,3}\.\d{1,3}$/,
    // IPv6 loopback / link-local / unique-local. URL hostnames bracket
    // literal v6 addresses (`[::1]`), but `URL.hostname` strips the
    // brackets — match the unbracketed form.
    /^::1$/,
    /^fe[89ab][0-9a-f]:/i,
    /^fc[0-9a-f][0-9a-f]:/i,
    /^fd[0-9a-f][0-9a-f]:/i,
    // Cloud / internal-DNS suffixes used as private resolvers.
    /\.internal$/i,
    /\.local$/i,
    /^metadata\.google\.internal$/i,
]

export function isUnsafeMcpHost(host: string): boolean {
    // `URL.hostname` keeps the brackets on IPv6 literals (`[::1]`,
    // `[fe80::1%eth0]`); strip them so the IPv6 patterns can match without
    // having to anchor on the bracket form too.
    const normalized = host.toLowerCase().replace(/^\[|\]$/g, '')
    return UNSAFE_HOST_PATTERNS.some((re) => re.test(normalized))
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
