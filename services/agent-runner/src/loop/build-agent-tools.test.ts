import { z } from 'zod'

import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    InProcessSandboxPool,
    MemoryBundleStore,
    ToolRefSchema,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { AgentToolDeps, buildAgentTools } from './build-agent-tools'

type ToolRefInput = z.input<typeof ToolRefSchema>

function makeRev(toolRefs: ToolRefInput[], skills: AgentRevision['spec']['skills'] = []): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'x', tools: toolRefs, skills }),
    }
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
})
