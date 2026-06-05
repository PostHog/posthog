import { z } from 'zod'

import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    InProcessSandboxPool,
    McpRef,
    MemoryBundleStore,
    ToolRefSchema,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { AgentToolDeps, buildAgentTools } from './build-agent-tools'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'

type ToolRefInput = z.input<typeof ToolRefSchema>

function makeRev(
    toolRefs: ToolRefInput[],
    skills: AgentRevision['spec']['skills'] = [],
    mcps: McpRef[] = []
): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'x', tools: toolRefs, skills, mcps }),
    }
}

/**
 * Stub `OpenedMcp` over an in-process tool table — fast, deterministic, and
 * keeps these tests focused on the adapter logic. PR 2's `mcp-clients.test.ts`
 * already exercises the real SDK round-trip via `InMemoryTransport`.
 */
function makeFakeMcp(
    prefix: string,
    ref: McpRef,
    handlers: Record<
        string,
        { description: string; inputSchema?: unknown; handler: (args: Record<string, unknown>) => Promise<unknown> }
    >
): OpenedMcp {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = []
    const opened: OpenedMcp & { calls: typeof calls } = {
        prefix,
        ref,
        listTools: async () => {
            const out: RemoteMcpTool[] = []
            for (const [name, h] of Object.entries(handlers)) {
                out.push({ name, description: h.description, inputSchema: h.inputSchema ?? { type: 'object' } })
            }
            return out
        },
        callTool: async (name, args) => {
            calls.push({ name, args })
            const h = handlers[name]
            if (!h) {
                return {
                    content: [{ type: 'text' as const, text: `unknown_tool: ${name}` }],
                    isError: true,
                }
            }
            try {
                const result = await h.handler(args)
                return {
                    content: [{ type: 'text' as const, text: JSON.stringify(result) }],
                    structuredContent: result as Record<string, unknown>,
                }
            } catch (err) {
                return {
                    content: [{ type: 'text' as const, text: (err as Error).message }],
                    isError: true,
                }
            }
        },
        close: async () => undefined,
        calls,
    }
    return opened
}

function makeSession(): AgentSession {
    return {
        id: 's1',
        application_id: 'app1',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        acl: [],
        pending_elevation_requests: [],
        failure_reason: null,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

function makeDeps(rev: AgentRevision, over: Partial<AgentToolDeps> = {}): AgentToolDeps {
    return {
        rev,
        session: makeSession(),
        sandbox: null,
        integrations: {},
        secrets: {},
        bundle: new MemoryBundleStore(),
        log: () => undefined,
        ...over,
    }
}

function byId(
    built: Awaited<ReturnType<typeof buildAgentTools>>,
    id: string
): Awaited<ReturnType<typeof buildAgentTools>>['tools'][number] {
    const tool = built.tools.find((t) => t.label === id)
    if (!tool) {
        throw new Error(`tool ${id} not built`)
    }
    return tool
}

describe('buildAgentTools', () => {
    it('always includes the two meta control-flow tools; load-skill only with skills', async () => {
        const noSkills = await buildAgentTools(makeRev([]), makeDeps(makeRev([])))
        expect(noSkills.tools.map((t) => t.label).sort()).toEqual([
            '@posthog/meta-end-session',
            '@posthog/meta-end-turn',
        ])

        const rev = makeRev([], [{ id: 'research', path: 'skills/research.md', description: 'd' }])
        const withSkills = await buildAgentTools(rev, makeDeps(rev))
        expect(withSkills.tools.map((t) => t.label)).toContain('@posthog/load-skill')
    })

    it('maps provider-safe names back to original ids', async () => {
        const rev = makeRev([{ kind: 'native', id: '@posthog/query' }])
        const built = await buildAgentTools(rev, makeDeps(rev))
        expect(built.nameToId.get('_posthog_query')).toBe('@posthog/query')
        // Tools are registered under their original id; the safe form is only
        // applied on the wire by the driver's streamFn.
        expect(byId(built, '@posthog/query').name).toBe('@posthog/query')
    })

    it('meta-end-turn terminates with an end_turn control detail', async () => {
        const built = await buildAgentTools(makeRev([]), makeDeps(makeRev([])))
        const endTurn = await byId(built, '@posthog/meta-end-turn').execute('c1', {})
        expect(endTurn).toEqual({
            content: [{ type: 'text', text: JSON.stringify({ ended_turn: true }) }],
            details: { control: { kind: 'end_turn' } },
            terminate: true,
        })
    })

    it('meta-end-session terminates with a close control detail carrying the summary', async () => {
        const built = await buildAgentTools(makeRev([]), makeDeps(makeRev([])))
        const close = await byId(built, '@posthog/meta-end-session').execute('c3', { summary: 'done' })
        expect(close).toEqual({
            content: [{ type: 'text', text: JSON.stringify({ ended: true }) }],
            details: { control: { kind: 'close', summary: 'done' } },
            terminate: true,
        })
    })

    it('native tool execute calls native.run and returns JSON content + raw output detail', async () => {
        setPosthogInternalClient({
            async runHogql() {
                return { rows: [{ a: 1 }], columns: ['a'] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
        const rev = makeRev([{ kind: 'native', id: '@posthog/query' }])
        const built = await buildAgentTools(rev, makeDeps(rev))
        const result = await byId(built, '@posthog/query').execute('c1', { query: 'select 1 as a' })
        expect(result.content).toEqual([{ type: 'text', text: JSON.stringify({ rows: [{ a: 1 }], columns: ['a'] }) }])
        expect(result.details.output).toEqual({ rows: [{ a: 1 }], columns: ['a'] })
    })

    it('native execute lets a thrown error propagate (the loop renders it as an error result)', async () => {
        setPosthogInternalClient({
            async runHogql() {
                throw new Error('boom')
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
        const rev = makeRev([{ kind: 'native', id: '@posthog/query' }])
        const built = await buildAgentTools(rev, makeDeps(rev))
        await expect(byId(built, '@posthog/query').execute('c1', { query: 'x' })).rejects.toThrow('boom')
    })

    it('skips an unknown native id in the spec', async () => {
        const rev = makeRev([{ kind: 'native', id: '@posthog/does-not-exist' }])
        const built = await buildAgentTools(rev, makeDeps(rev))
        expect(built.tools.map((t) => t.label)).not.toContain('@posthog/does-not-exist')
    })

    it('custom tool execute routes to the sandbox', async () => {
        const COMPILED = `
            module.exports = {
                id: "fetch-acme",
                actions: { default: (args) => ({ greeted: args.name }) },
            }
        `
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's1',
            teamId: 1,
            tools: [{ id: 'fetch-acme', compiledJs: COMPILED, schemaJson: {} }],
            nonces: {},
        })
        const rev = makeRev([{ kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' }])
        const built = await buildAgentTools(rev, makeDeps(rev, { sandbox }))
        const result = await byId(built, 'fetch-acme').execute('c1', { name: 'world' })
        expect(result.content).toEqual([{ type: 'text', text: JSON.stringify({ greeted: 'world' }) }])
        await pool.release('s1')
    })

    it('custom tool execute throws when no sandbox is wired', async () => {
        const rev = makeRev([{ kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' }])
        const built = await buildAgentTools(rev, makeDeps(rev, { sandbox: null }))
        await expect(byId(built, 'fetch-acme').execute('c1', {})).rejects.toThrow(/requires a sandbox/)
    })

    it('custom tool description + parameters load from schema.json in the bundle', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write(
            'rev1',
            'tools/fetch-acme/schema.json',
            JSON.stringify({
                description: 'Fetch from Acme',
                args: { type: 'object', properties: { name: { type: 'string' } } },
            })
        )
        const rev = makeRev([{ kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' }])
        const built = await buildAgentTools(rev, makeDeps(rev, { bundle }))
        const tool = byId(built, 'fetch-acme')
        expect(tool.description).toBe('Fetch from Acme')
        expect(tool.parameters).toEqual({ type: 'object', properties: { name: { type: 'string' } } })
    })

    describe('mcp tools', () => {
        it('emits one AgentTool per remote tool, name-prefixed with the client prefix', async () => {
            const ref: McpRef = { id: 'linear', url: 'https://example.com/linear', secrets: [] }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': { description: 'Open a new Linear issue.', handler: async () => ({}) },
                'list-issues': { description: 'List recent Linear issues.', handler: async () => ({}) },
            })
            const rev = makeRev([], [], [ref])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            const names = built.tools.map((t) => t.label).sort()
            expect(names).toContain('linear__create-issue')
            expect(names).toContain('linear__list-issues')
        })

        it('filters remote tools through ref.tools[] bare-string entries (empty/omitted = expose all)', async () => {
            // Post-PR-7: bare-string entries in `tools[]` preserve the old
            // `allowlist[]` inclusion semantics. Object-form entries also
            // count toward inclusion via their `name` field — covered in the
            // approval-wrap suite (commit B).
            const ref: McpRef = {
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                tools: ['list-issues'],
            }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': { description: 'Open a new Linear issue.', handler: async () => ({}) },
                'list-issues': { description: 'List recent Linear issues.', handler: async () => ({}) },
            })
            const rev = makeRev([], [], [ref])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            const names = built.tools.map((t) => t.label)
            expect(names).toContain('linear__list-issues')
            expect(names).not.toContain('linear__create-issue')
        })

        it('execute dispatches through the open client and surfaces structured output', async () => {
            const ref: McpRef = { id: 'linear', url: 'https://example.com/linear', secrets: [] }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': {
                    description: 'Open a new Linear issue.',
                    handler: async (args) => ({ id: 'ISS-42', title: args.title }),
                },
            })
            const rev = makeRev([], [], [ref])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            const result = await byId(built, 'linear__create-issue').execute('c1', { title: 'fix the thing' })
            // Content stringifies the raw MCP envelope — matches the wire shape
            // every other tool source produces.
            expect(typeof (result.content[0] as { text?: string }).text).toBe('string')
            // The structured envelope lives on details.output for spans/analytics.
            const envelope = result.details.output as { structuredContent?: { id?: string; title?: string } }
            expect(envelope.structuredContent?.id).toBe('ISS-42')
            expect(envelope.structuredContent?.title).toBe('fix the thing')
        })

        it('execute throws when the remote returns isError so the loop renders an error tool_result', async () => {
            const ref: McpRef = { id: 'linear', url: 'https://example.com/linear', secrets: [] }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': {
                    description: 'Open a new Linear issue.',
                    handler: async () => {
                        throw new Error('remote_blew_up')
                    },
                },
            })
            const rev = makeRev([], [], [ref])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            await expect(byId(built, 'linear__create-issue').execute('c1', {})).rejects.toThrow('remote_blew_up')
        })

        it('skips a remote tool whose prefixed name collides with an already-built tool', async () => {
            // Custom tool `linear__create-issue` plus an MCP `linear` exposing
            // `create-issue` would collapse to the same exposed id. We keep
            // the first one (the custom tool) and silently skip the duplicate
            // — matches the dup-id semantics of spec.tools[].
            const ref: McpRef = { id: 'linear', url: 'https://example.com/linear', secrets: [] }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': { description: 'Open a Linear issue.', handler: async () => ({}) },
            })
            const rev = makeRev(
                [{ kind: 'custom', id: 'linear__create-issue', path: 'tools/linear-create-issue/' }],
                [],
                [ref]
            )
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            const matches = built.tools.filter((t) => t.label === 'linear__create-issue')
            expect(matches).toHaveLength(1)
            // The first registration wins — the custom one, which routes through
            // the (absent) sandbox.
            await expect(matches[0].execute('c1', {})).rejects.toThrow(/requires a sandbox/)
        })

        it('walks multiple opened clients and surfaces all their tools', async () => {
            const linearRef: McpRef = {
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
            }
            const githubRef: McpRef = {
                id: 'github',
                url: 'https://example.com/github',
                secrets: [],
            }
            const linear = makeFakeMcp('linear', linearRef, {
                'create-issue': { description: 'd', handler: async () => ({}) },
            })
            const github = makeFakeMcp('github', githubRef, {
                'create-issue': { description: 'd', handler: async () => ({}) },
            })
            const rev = makeRev([], [], [linearRef, githubRef])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [linear, github] }))
            const names = built.tools.map((t) => t.label).sort()
            expect(names).toContain('linear__create-issue')
            expect(names).toContain('github__create-issue')
        })

        it('keeps the provider-safe name map keyed by the prefixed id', async () => {
            const ref: McpRef = { id: 'linear', url: 'https://example.com/linear', secrets: [] }
            const mcp = makeFakeMcp('linear', ref, {
                'create-issue': { description: 'd', handler: async () => ({}) },
            })
            const rev = makeRev([], [], [ref])
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            // `__` and `-` are both already in the safe charset, so the safe
            // form is identical to the original. The map still includes it so
            // the streamFn's reverse lookup is consistent.
            expect(built.nameToId.get('linear__create-issue')).toBe('linear__create-issue')
        })

        it('wraps a listTools() failure with mcp_list_tools_failed:<prefix>', async () => {
            // Without the wrapping, an SDK-internal error string would surface
            // as the session-failure reason — making it hard to attribute the
            // outage to a specific MCP at triage time.
            const ref: McpRef = { id: 'flaky', url: 'https://example.com/flaky', secrets: [] }
            const brokenClient: OpenedMcp = {
                prefix: 'flaky',
                ref,
                listTools: async () => {
                    throw new Error('socket hang up')
                },
                // Never called — listTools throws before any tool is registered.
                callTool: async () => ({ content: [] }) as unknown as Awaited<ReturnType<OpenedMcp['callTool']>>,
                close: async () => undefined,
            }
            const rev = makeRev([], [], [ref])
            await expect(buildAgentTools(rev, makeDeps(rev, { mcpClients: [brokenClient] }))).rejects.toThrow(
                /mcp_list_tools_failed:flaky: socket hang up/
            )
        })
    })
})
