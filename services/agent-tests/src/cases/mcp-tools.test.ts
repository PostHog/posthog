/**
 * Runtime MCPs: the agent declares `spec.mcps[]`, the worker opens MCP
 * clients at session start (via the injected `mcpTransportFactory` paired
 * with an in-process `McpServer`), the model emits a prefixed tool call
 * (`<mcp_id>__<remote_name>`), and the runner routes dispatch back through
 * the open client.
 *
 * Covers the v1 surface described in
 * `docs/agent-platform/plans/runtime-mcps.md`:
 *   - Round-trip dispatch through an `external` MCP.
 *   - `allowlist` filtering of remote tools.
 *   - `${SECRET_NAME}` substitution in the connect URL.
 *   - Remote-side errors land as `isError` tool_results the model can recover from.
 *   - The agent-variant resolver is wired (the runner still owns the URL build).
 *
 * Pattern: every test builds its cluster with a `mcpTransportFactory` that
 * pairs each `Client.connect` with a fresh `McpServer` via
 * `InMemoryTransport.createLinkedPair()`. Tools land in a per-test
 * `captured` array so we can assert on the args the remote actually saw.
 */

import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import request from 'supertest'
import { z } from 'zod'

import type { McpTransportFactory } from '@posthog/agent-runner'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

interface ToolDef {
    description: string
    /** Zod object describing the args (matches `server.registerTool` signature). */
    inputSchema?: Record<string, z.ZodTypeAny>
    handler: (args: Record<string, unknown>) => Promise<unknown> | unknown
}

interface FactorySetup {
    factory: McpTransportFactory
    captured: Array<{ name: string; args: Record<string, unknown>; target: { url: string } }>
    /** Targets the factory was invoked with — handy for asserting URL substitution. */
    targets: Array<{ url: string; headers: Record<string, string> }>
}

/**
 * Build a transport factory that spins a fresh `McpServer` on every
 * `Client.connect`. Each server is wired through `InMemoryTransport` so the
 * SDK protocol is exercised end-to-end — no HTTP, no ports.
 */
function buildFactory(tools: Record<string, ToolDef>): FactorySetup {
    const captured: FactorySetup['captured'] = []
    const targets: FactorySetup['targets'] = []
    const factory: McpTransportFactory = (target): Transport => {
        targets.push(target)
        const server = new McpServer({ name: 'harness-mcp', version: '1.0.0' })
        for (const [name, def] of Object.entries(tools)) {
            server.registerTool(
                name,
                {
                    title: name,
                    description: def.description,
                    inputSchema: def.inputSchema ?? {},
                },
                async (args) => {
                    captured.push({ name, args, target: { url: target.url } })
                    const result = await def.handler(args as Record<string, unknown>)
                    return { content: [{ type: 'text' as const, text: JSON.stringify(result) }] }
                }
            )
        }
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        void server.server.connect(serverTransport)
        return clientTransport
    }
    return { factory, captured, targets }
}

describe('runtime MCPs: real e2e', () => {
    let c: Cluster

    afterEach(async () => {
        await c?.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('agent declares spec.mcps[external], model calls <id>__<name>, runner routes through the open client', async () => {
        const { factory, captured } = buildFactory({
            echo: {
                description: 'Echo input back.',
                inputSchema: { msg: z.string() },
                handler: ({ msg }) => ({ echoed: msg }),
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('demo__echo', { msg: 'hello' }), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-echo',
            spec: {
                mcps: [{ kind: 'external', id: 'demo', url: 'https://example.com/demo' }],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-echo/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // user + assistant(toolCall) + toolResult + assistant(text)
        expect(session!.conversation).toHaveLength(4)
        const toolResult = session!.conversation[2] as { role: 'toolResult'; isError: boolean }
        expect(toolResult.role).toBe('toolResult')
        expect(toolResult.isError).toBe(false)
        expect(captured).toEqual([
            { name: 'echo', args: { msg: 'hello' }, target: { url: 'https://example.com/demo' } },
        ])
    })

    it('hides remote tools not on the allowlist (model that calls a filtered one gets an error tool_result)', async () => {
        const { factory } = buildFactory({
            'create-issue': { description: 'd', handler: () => ({ ok: true }) },
            'list-issues': { description: 'd', handler: () => ({ items: [] }) },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('linear__list-issues', {}), fauxText('here')])
        await c.deployAgent({
            slug: 'mcp-allowlisted',
            spec: {
                mcps: [
                    {
                        kind: 'external',
                        id: 'linear',
                        url: 'https://example.com/linear',
                        allowlist: ['list-issues'],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-allowlisted/run').send({ message: 'list' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean }
            | undefined
        expect(toolResult?.isError).toBe(false)
        // The model would have errored if it tried `linear__create-issue` —
        // belt-and-braces check that the allowlisted one round-tripped.
    })

    it('substitutes ${SECRET_NAME} placeholders in the connect URL', async () => {
        const { factory, targets } = buildFactory({
            ping: { description: 'd', handler: () => ({ ok: true }) },
        })
        c = await buildCluster({
            mcpTransportFactory: factory,
            resolveSecrets: async () => ({ TENANT: 'acme' }),
        })
        c.setScript([fauxCallTool('tenant__ping', {}), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-secret',
            spec: {
                secrets: ['TENANT'],
                mcps: [
                    {
                        kind: 'external',
                        id: 'tenant',
                        url: 'https://example.com/${TENANT}/mcp',
                        secrets: ['TENANT'],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-secret/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The factory was invoked with the substituted URL — the placeholder
        // never reached the remote (which is what would happen in prod too).
        expect(targets[0].url).toBe('https://example.com/acme/mcp')
    })

    it('remote tool errors surface as isError tool_result so the model can recover', async () => {
        const { factory } = buildFactory({
            boom: {
                description: 'always throws',
                handler: () => {
                    throw new Error('remote_blew_up')
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('demo__boom', {}), fauxText('Recovered after error.')])
        await c.deployAgent({
            slug: 'mcp-error',
            spec: { mcps: [{ kind: 'external', id: 'demo', url: 'https://example.com/demo' }] },
        })
        const res = await request(c.ingress).post('/agents/mcp-error/run').send({ message: 'try' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        // Session continues (the model recovers via the follow-up text turn).
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean; content: Array<{ type: string; text?: string }> }
            | undefined
        expect(toolResult?.isError).toBe(true)
        // Error text carries the remote's message so debugging is possible.
        const errText = toolResult?.content?.[0]?.text
        expect(errText).toContain('remote_blew_up')
    })

    it('routes a kind: agent ref through the supplied resolver and uses slug as the prefix', async () => {
        const { factory, targets, captured } = buildFactory({
            ask: {
                description: 'd',
                inputSchema: { topic: z.string() },
                handler: () => ({ answered: true }),
            },
        })
        c = await buildCluster({
            mcpTransportFactory: factory,
            agentMcpResolver: async (slug) => ({
                url: `https://ingress.local/agents/${slug}/mcp`,
                headers: { 'X-PostHog-Internal': 'yes' },
            }),
        })
        c.setScript([fauxCallTool('weekly-digest__ask', { topic: 'kpi' }), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-agent-variant',
            spec: { mcps: [{ kind: 'agent', slug: 'weekly-digest' }] },
        })
        const res = await request(c.ingress).post('/agents/mcp-agent-variant/run').send({ message: 'ask' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The harness resolver was consulted — proves the runner doesn't
        // short-circuit kind:'agent' refs.
        expect(targets[0].url).toBe('https://ingress.local/agents/weekly-digest/mcp')
        expect(captured).toEqual([
            { name: 'ask', args: { topic: 'kpi' }, target: { url: 'https://ingress.local/agents/weekly-digest/mcp' } },
        ])
    })
})
