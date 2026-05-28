import {
    AgentRevision,
    AgentSpecSchema,
    InProcessSandboxPool,
    MemoryBundleStore,
    Sandbox,
} from '@posthog/agent-shared-v2'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { dispatchTool } from './tool-dispatch'

function makeRev(
    toolRefs: AgentRevision['spec']['tools'],
    skills: AgentRevision['spec']['skills'] = []
): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by: 'u',
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'x', tools: toolRefs, skills }),
    }
}

describe('dispatchTool', () => {
    const baseInput = {
        teamId: 1,
        sessionId: 's1',
        sandbox: null as Sandbox | null,
        integrations: {},
        secret: () => undefined,
        log: () => undefined,
    }

    it('returns suspend on @posthog/meta-ask-for-input', async () => {
        const out = await dispatchTool({ ...baseInput, rev: makeRev([]) }, '@posthog/meta-ask-for-input', {
            prompt: 'Need approval?',
        })
        expect(out).toEqual({ kind: 'suspend', prompt: 'Need approval?' })
    })

    it('returns end on @posthog/meta-end-session', async () => {
        const out = await dispatchTool({ ...baseInput, rev: makeRev([]) }, '@posthog/meta-end-session', {
            summary: 'done',
        })
        expect(out).toEqual({ kind: 'end', summary: 'done' })
    })

    it('dispatches a native tool referenced in the revision', async () => {
        setPosthogInternalClient({
            async runHogql() {
                return { rows: [{ a: 1 }], columns: ['a'] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([{ kind: 'native', id: '@posthog/query' }]),
            },
            '@posthog/query',
            { query: 'select 1 as a' }
        )
        expect(out).toEqual({ kind: 'ok', result: { rows: [{ a: 1 }], columns: ['a'] } })
    })

    it('returns error if native tool args fail schema', async () => {
        setPosthogInternalClient({
            async runHogql() {
                return { rows: [], columns: [] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([{ kind: 'native', id: '@posthog/query' }]),
            },
            '@posthog/query',
            { query: '' }
        )
        expect(out.kind).toBe('error')
    })

    it('rejects a tool not in the revision', async () => {
        const out = await dispatchTool({ ...baseInput, rev: makeRev([]) }, '@posthog/slack-post-message', {})
        expect(out.kind).toBe('error')
        expect(out.kind === 'error' && out.message).toMatch(/not in revision/)
    })

    it('dispatches a custom tool via sandbox', async () => {
        const COMPILED = `
            module.exports = {
                id: "fetch-acme",
                actions: {
                    default: (args) => ({ greeted: args.name }),
                },
            }
        `
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's1',
            teamId: 1,
            tools: [{ id: 'fetch-acme', compiledJs: COMPILED, schemaJson: {} }],
            nonces: {},
        })
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([{ kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' }]),
                sandbox,
            },
            'fetch-acme',
            { name: 'world' }
        )
        expect(out).toEqual({ kind: 'ok', result: { greeted: 'world' } })
        await pool.release('s1')
    })

    it('errors when custom tool has no sandbox', async () => {
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([{ kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' }]),
            },
            'fetch-acme',
            {}
        )
        expect(out.kind).toBe('error')
    })

    it('@posthog/load-skill returns the body of a known skill from the bundle', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'skills/research.md', 'Body of the research skill.')
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([], [{ id: 'research', path: 'skills/research.md', description: 'How to research' }]),
                bundle,
            },
            '@posthog/load-skill',
            { id: 'research' }
        )
        expect(out.kind).toBe('ok')
        expect(out.kind === 'ok' && out.result).toEqual({ id: 'research', body: 'Body of the research skill.' })
    })

    it('@posthog/load-skill errors on an unknown skill id', async () => {
        const bundle = new MemoryBundleStore()
        const out = await dispatchTool(
            {
                ...baseInput,
                rev: makeRev([], [{ id: 'research', path: 'skills/research.md' }]),
                bundle,
            },
            '@posthog/load-skill',
            { id: 'ghost' }
        )
        expect(out.kind).toBe('error')
        expect(out.kind === 'error' && out.message).toMatch(/unknown skill id/)
    })
})
