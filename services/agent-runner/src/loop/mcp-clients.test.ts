/**
 * Unit tests for `loop/mcp-clients.ts`. Uses the SDK's `InMemoryTransport`
 * paired with a real `McpServer` so the round-trip exercises the actual
 * protocol — same pattern as `services/mcp/tests/unit/exec-description-emission.test.ts`.
 *
 * The factory injection point (`transportFactory`) is the only thing the
 * tests need to substitute; the rest of the module's behaviour
 * (auth-header stamping, secret substitution, partial-open cleanup) gets
 * exercised through the real `Client` over the in-memory pipe.
 */

import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import { z } from 'zod'

import type { McpRef } from '@posthog/agent-shared'

import { McpTransportFactory, openMcpClients } from './mcp-clients'

type ToolCapturedCall = { name: string; args: Record<string, unknown>; headers: Record<string, string> | null }

/**
 * Spin up a tiny `McpServer` exposing `echo` + `boom` tools, return a transport
 * factory that pairs every connect with a fresh server instance. Captured
 * tool calls land in the returned array so tests can assert what the remote
 * actually saw.
 *
 * `pairs` is the inflight server handles keyed by the prefix the test gives
 * the factory — tests use it to close servers in their own `afterEach`.
 */
interface PairHandle {
    close: () => Promise<void>
    /**
     * Flips to true the first time the SDK calls `close()` on the
     * server-side transport — i.e. when the *runner* closed the
     * matching client. Used to verify the partial-open cleanup path
     * actually drains successful clients rather than leaking them.
     */
    serverClosed: { value: boolean }
}

async function buildEchoFactory(): Promise<{
    factory: McpTransportFactory
    calls: ToolCapturedCall[]
    pairs: PairHandle[]
    /**
     * Tracks the `{ url, headers }` payloads the factory was invoked with —
     * lets tests assert auth/secret substitution without parsing HTTP traffic.
     */
    targets: Array<{ url: string; headers: Record<string, string> }>
}> {
    const calls: ToolCapturedCall[] = []
    const pairs: PairHandle[] = []
    const targets: Array<{ url: string; headers: Record<string, string> }> = []
    const factory: McpTransportFactory = (target): Transport => {
        targets.push(target)
        const server = new McpServer({ name: 'echo-mcp', version: '1.0.0' })
        server.registerTool(
            'echo',
            {
                title: 'Echo',
                description: 'Echo the input back as text.',
                inputSchema: { msg: z.string() },
            },
            async ({ msg }) => {
                calls.push({ name: 'echo', args: { msg }, headers: null })
                return { content: [{ type: 'text' as const, text: msg }] }
            }
        )
        server.registerTool(
            'boom',
            {
                title: 'Boom',
                description: 'Always throws — used to exercise the error path.',
                inputSchema: {},
            },
            async () => {
                calls.push({ name: 'boom', args: {}, headers: null })
                throw new Error('boom_intentional')
            }
        )
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        // Connect the server side eagerly — the SDK's `connect()` is fire-and-
        // forget at this layer; the linked pair carries the handshake.
        void server.server.connect(serverTransport)
        const serverClosed = { value: false }
        const originalServerClose = serverTransport.close?.bind(serverTransport)
        serverTransport.close = async () => {
            serverClosed.value = true
            await originalServerClose?.()
        }
        pairs.push({
            close: async () => {
                await clientTransport.close?.()
                await serverTransport.close?.()
            },
            serverClosed,
        })
        return clientTransport
    }
    return { factory, calls, pairs, targets }
}

async function closePairs(pairs: { close: () => Promise<void> }[]): Promise<void> {
    await Promise.all(pairs.map((p) => p.close()))
}

describe('openMcpClients', () => {
    it('returns an empty result for an empty refs list', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const { clients, close } = await openMcpClients([], {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(targets).toEqual([]) // factory never invoked
        await close()
        await closePairs(pairs)
    })

    it('opens an external ref and lists+calls remote tools', async () => {
        const { factory, calls, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ kind: 'external', id: 'echo', url: 'https://example.com/mcp', secrets: [] }]

        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })

        expect(clients).toHaveLength(1)
        expect(clients[0].prefix).toBe('echo')
        expect(clients[0].ref).toEqual(refs[0])

        const listed = await clients[0].listTools()
        const names = listed.map((t) => t.name).sort()
        expect(names).toEqual(['boom', 'echo'])
        expect(listed.find((t) => t.name === 'echo')?.description).toBe('Echo the input back as text.')

        const result = await clients[0].callTool('echo', { msg: 'hello' })
        expect(calls).toEqual([{ name: 'echo', args: { msg: 'hello' }, headers: null }])
        const text = (result.content as Array<{ type: string; text?: string }>)[0]
        expect(text.type).toBe('text')
        expect(text.text).toBe('hello')

        await close()
        await closePairs(pairs)
    })

    it('preserves the prefix as the entry id for external refs', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            { kind: 'external', id: 'linear', url: 'https://example.com/linear', secrets: [] },
            { kind: 'external', id: 'github', url: 'https://example.com/github', secrets: [] },
        ]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients.map((c) => c.prefix).sort()).toEqual(['github', 'linear'])
        await close()
        await closePairs(pairs)
    })

    it('rejects duplicate prefixes across refs', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            { kind: 'external', id: 'dup', url: 'https://example.com/a', secrets: [] },
            { kind: 'external', id: 'dup', url: 'https://example.com/b', secrets: [] },
        ]
        await expect(
            openMcpClients(refs, { integrations: {}, secrets: {}, transportFactory: factory })
        ).rejects.toThrow(/duplicate_mcp_prefix: dup/)
        // The duplicate-prefix path closes the clients it opened — the in-memory
        // server pairs should still be drain-able by the test's own cleanup.
        await closePairs(pairs)
    })

    it('substitutes ${NAME} placeholders in url from secrets', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'tenant',
                url: 'https://example.com/${TENANT}/mcp',
                secrets: ['TENANT'],
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {},
            secrets: { TENANT: 'acme' },
            transportFactory: factory,
        })
        expect(targets).toHaveLength(1)
        expect(targets[0].url).toBe('https://example.com/acme/mcp')
        await close()
        await closePairs(pairs)
    })

    it('throws mcp_secret_not_resolved when a declared secret is missing', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'tenant',
                url: 'https://example.com/${TENANT}/mcp',
                secrets: ['TENANT'],
            },
        ]
        await expect(
            openMcpClients(refs, { integrations: {}, secrets: {}, transportFactory: factory })
        ).rejects.toThrow(/mcp_secret_not_resolved: TENANT/)
        await closePairs(pairs)
    })

    it('stamps Authorization: Bearer <token> when auth.integration is set and the validator allows the host', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {
                'linear:T01': { kind: 'linear', access_token: 'tok_abc' },
            },
            secrets: {},
            transportFactory: factory,
            integrationHostValidator: () => true,
        })
        expect(targets[0].headers).toEqual({ Authorization: 'Bearer tok_abc' })
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer when no host validator is wired', async () => {
        // Fail-closed: a deploy that doesn't wire `integrationHostValidator`
        // must NOT silently regress to "attach bearer to whatever URL the
        // spec author chose." Without this, a malicious author could point
        // at their own URL and harvest the team's OAuth token.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        await expect(
            openMcpClients(refs, {
                integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
                secrets: {},
                transportFactory: factory,
            })
        ).rejects.toThrow(/mcp_integration_host_validator_not_wired: linear:T01/)
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer when validator rejects the host', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'linear',
                url: 'https://evil.example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        await expect(
            openMcpClients(refs, {
                integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
                secrets: {},
                transportFactory: factory,
                integrationHostValidator: (ref, url) =>
                    // Mimic a prod validator that only allows the canonical
                    // host for a known integration kind.
                    ref === 'linear:T01' && url.host === 'mcp.linear.app',
            })
        ).rejects.toThrow(/mcp_integration_host_not_allowed: linear:T01 → evil\.example\.com/)
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer over plaintext http even when the host is allowed', async () => {
        // Smokescreen owns SSRF but filters by destination, not scheme — it
        // won't stop the team's OAuth bearer being sent in cleartext to an
        // allowlisted public host. The host validator only checks `url.host`,
        // so the https-only guard is the runner's job on the credential path.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'linear',
                url: 'http://mcp.linear.app/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        await expect(
            openMcpClients(refs, {
                integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
                secrets: {},
                transportFactory: factory,
                // Host is allowed — only the scheme should reject it.
                integrationHostValidator: () => true,
            })
        ).rejects.toThrow(/mcp_integration_unsafe_scheme: linear:T01 → http:/)
        await closePairs(pairs)
    })

    it('throws mcp_integration_not_resolved when the integration ref is missing', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                kind: 'external',
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        await expect(
            openMcpClients(refs, { integrations: {}, secrets: {}, transportFactory: factory })
        ).rejects.toThrow(/mcp_integration_not_resolved: linear:T01/)
        await closePairs(pairs)
    })

    it('throws agent_mcp_resolver_not_wired for kind: agent without a resolver', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ kind: 'agent', slug: 'weekly-digest' }]
        await expect(
            openMcpClients(refs, {
                integrations: {},
                secrets: {},
                transportFactory: factory,
                callerContext: { teamId: 1, sessionId: 's1' },
            })
        ).rejects.toThrow(/agent_mcp_resolver_not_wired/)
        await closePairs(pairs)
    })

    it('throws agent_mcp_caller_context_missing when an agent ref needs but lacks ctx', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ kind: 'agent', slug: 'weekly-digest' }]
        await expect(
            openMcpClients(refs, {
                integrations: {},
                secrets: {},
                transportFactory: factory,
                agentMcpResolver: async (slug) => ({ url: `https://ingress/${slug}`, headers: {} }),
                // callerContext deliberately omitted — proves the runner
                // protects the resolver from a missing-isolation case rather
                // than letting it silently see `undefined`.
            })
        ).rejects.toThrow(/agent_mcp_caller_context_missing/)
        await closePairs(pairs)
    })

    it('delegates kind: agent to the supplied resolver, passing slug + caller ctx', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [{ kind: 'agent', slug: 'weekly-digest' }]
        const seenCtx: Array<{ slug: string; teamId: number; sessionId: string }> = []
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
            callerContext: { teamId: 42, sessionId: 'sess-abc' },
            agentMcpResolver: async (slug, ctx) => {
                seenCtx.push({ slug, ...ctx })
                return {
                    url: `https://ingress.local/teams/${ctx.teamId}/agents/${slug}/mcp`,
                    headers: { 'X-PostHog-Internal': 'yes', 'X-Session-Id': ctx.sessionId },
                }
            },
        })
        expect(clients[0].prefix).toBe('weekly-digest')
        expect(seenCtx).toEqual([{ slug: 'weekly-digest', teamId: 42, sessionId: 'sess-abc' }])
        expect(targets[0].url).toBe('https://ingress.local/teams/42/agents/weekly-digest/mcp')
        expect(targets[0].headers['X-PostHog-Internal']).toBe('yes')
        expect(targets[0].headers['X-Session-Id']).toBe('sess-abc')
        await close()
        await closePairs(pairs)
    })

    it('on partial-open failure: closes successful clients and rethrows', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        // First ref opens cleanly; second ref fails during target resolution
        // (missing integration) — the cleanup path should close the first
        // client without leaving pending writes on the in-memory pair.
        const refs: McpRef[] = [
            { kind: 'external', id: 'ok', url: 'https://example.com/a', secrets: [] },
            {
                kind: 'external',
                id: 'broken',
                url: 'https://example.com/b',
                secrets: [],
                auth: { integration: 'missing' },
            },
        ]
        await expect(
            openMcpClients(refs, { integrations: {}, secrets: {}, transportFactory: factory })
        ).rejects.toThrow(/mcp_integration_not_resolved/)
        // Confirms the factory was invoked for the good ref (the partial-open
        // case is the one we actually want to cover).
        expect(targets.length).toBeGreaterThanOrEqual(1)
        // The contract this test exists for: the successful `ok` client must
        // have been closed by the cleanup path. Without this assertion an
        // accidental no-op on `closeAll(opened)` would still let the test
        // pass because `closePairs` below drains everything anyway. Look at
        // the pair created for the `ok` ref (the first factory invocation).
        const okPair = pairs[0]
        expect(okPair).not.toBeUndefined()
        expect(okPair.serverClosed.value).toBe(true)
        await closePairs(pairs)
    })

    it('surfaces remote tool errors as isError on the McpCallResult', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ kind: 'external', id: 'echo', url: 'https://example.com/mcp', secrets: [] }]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        const result = await clients[0].callTool('boom', {})
        // The SDK shapes thrown handler errors as `{ content: [...], isError: true }`
        // instead of rejecting — buildAgentTools (PR 3) is what decides to turn
        // that into a thrown error for the loop.
        expect(result.isError).toBe(true)
        await close()
        await closePairs(pairs)
    })

    it('uses the prefix on log warnings when close fails', async () => {
        const warnings: Array<{ msg: string; meta?: Record<string, unknown> }> = []
        // Override the factory so close() rejects — exercises the catch in
        // openOne's returned `close()` closure.
        const { factory: echoFactory, pairs } = await buildEchoFactory()
        const factory: McpTransportFactory = (target) => {
            const inner = echoFactory(target)
            // Wrap to override close — but only the client side, so the test
            // can still drain the in-memory pair via its own pairs[] entry.
            return new Proxy(inner, {
                get(t, prop, recv) {
                    if (prop === 'close') {
                        return async () => {
                            throw new Error('explode_on_close')
                        }
                    }
                    const v = Reflect.get(t, prop, recv)
                    return typeof v === 'function' ? v.bind(t) : v
                },
            }) as Transport
        }
        const refs: McpRef[] = [{ kind: 'external', id: 'echo', url: 'https://example.com/mcp', secrets: [] }]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
            log: (level, msg, meta) => {
                if (level === 'warn') {
                    warnings.push({ msg, meta })
                }
            },
        })
        await clients[0].close()
        expect(warnings.some((w) => w.msg === 'mcp.close.failed' && w.meta?.prefix === 'echo')).toBe(true)
        // Calling close() again via the batched closer just re-runs the same
        // path; we already asserted the per-client closure logged once.
        await close()
        await closePairs(pairs)
    })

    describe('devMcpBearerToken (dev-only auth fallback)', () => {
        it('attaches Authorization: Bearer when ref has no auth and a dev bearer is configured', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const { close } = await openMcpClients(
                [{ kind: 'external', id: 'x', url: 'https://mcp.example.com/sse', secrets: [] }],
                {
                    integrations: {},
                    secrets: {},
                    transportFactory: factory,
                    devMcpBearerToken: 'phx_dev_token',
                }
            )
            expect(targets[0].headers.Authorization).toBe('Bearer phx_dev_token')
            await close()
            await closePairs(pairs)
        })

        it('does NOT attach the dev bearer when ref.auth.integration is set (integration wins)', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const ref: McpRef = {
                kind: 'external',
                id: 'x',
                url: 'https://mcp.example.com/sse',
                secrets: [],
                auth: { integration: 'linear:acme' },
            }
            const { close } = await openMcpClients([ref], {
                integrations: { 'linear:acme': { access_token: 'integration_token', kind: 'linear' } },
                secrets: {},
                transportFactory: factory,
                devMcpBearerToken: 'phx_dev_token',
                integrationHostValidator: () => true,
            })
            expect(targets[0].headers.Authorization).toBe('Bearer integration_token')
            await close()
            await closePairs(pairs)
        })

        it('omits Authorization entirely when neither auth.integration nor a dev bearer is set', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const { close } = await openMcpClients(
                [{ kind: 'external', id: 'x', url: 'https://mcp.example.com/sse', secrets: [] }],
                { integrations: {}, secrets: {}, transportFactory: factory }
            )
            expect(targets[0].headers.Authorization).toBeUndefined()
            await close()
            await closePairs(pairs)
        })
    })
})
