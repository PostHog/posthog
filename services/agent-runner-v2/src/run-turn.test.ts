import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    InProcessSandboxPool,
    MemoryBundleStore,
} from '@posthog/agent-shared-v2'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { endTurn, MockPiClient, toolUseTurn } from './pi-client'
import { runSession } from './run-turn'

function makeRev(spec: Partial<Parameters<typeof AgentSpecSchema.parse>[0]> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app',
        parent_revision_id: null,
        created_by: 'u',
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'claude-opus-4-7', ...spec }),
    }
}

function makeSession(): AgentSession {
    return {
        id: 'sess1',
        application_id: 'app',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hello' }],
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

describe('runSession', () => {
    beforeEach(() => {
        setPosthogInternalClient({
            async runHogql() {
                return { rows: [], columns: [] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
    })

    it('completes when the model returns end_turn', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'you are a bot')
        const pi = new MockPiClient([endTurn('hi back')])
        const rev = makeRev()
        const session = makeSession()
        const out = await runSession(rev, session, {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(1)
        expect(session.conversation).toHaveLength(2)
    })

    it('dispatches a native tool use, then completes', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new MockPiClient([
            toolUseTurn([{ type: 'tool_use', id: 'tu_1', name: 'posthog.query.v1', input: { query: 'select 1' } }]),
            endTurn('query ran'),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: 'posthog.query.v1' }] })
        const session = makeSession()
        const out = await runSession(rev, session, {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(2)
        // assistant tool_use turn + user tool_result + assistant final
        const lastUser = session.conversation[2] as { role: 'user'; content: unknown[] }
        expect(lastUser.role).toBe('user')
        expect(lastUser.content[0]).toMatchObject({ type: 'tool_result', tool_use_id: 'tu_1' })
    })

    it('returns state=waiting on meta.ask_for_input.v1', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new MockPiClient([
            toolUseTurn([
                {
                    type: 'tool_use',
                    id: 'tu_2',
                    name: 'meta.ask_for_input.v1',
                    input: { prompt: 'Continue?' },
                },
            ]),
        ])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('waiting')
        expect(out.state === 'waiting' && out.prompt).toBe('Continue?')
    })

    it('returns state=completed on meta.end_session.v1 with summary', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new MockPiClient([
            toolUseTurn([
                {
                    type: 'tool_use',
                    id: 'tu_3',
                    name: 'meta.end_session.v1',
                    input: { summary: 'all done' },
                },
            ]),
        ])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.state === 'completed' && out.summary).toBe('all done')
    })

    it('returns state=failed when max_turns exhausted', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new MockPiClient(
            Array(5).fill(
                toolUseTurn([{ type: 'tool_use', id: 'tu_loop', name: 'posthog.query.v1', input: { query: 'x' } }])
            )
        )
        const rev = makeRev({
            tools: [{ kind: 'native', id: 'posthog.query.v1' }],
            limits: { max_turns: 3, max_tool_calls: 10, max_wall_seconds: 60 },
        })
        const out = await runSession(rev, makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('failed')
        expect(out.state === 'failed' && out.reason).toBe('max_turns_exceeded')
    })

    it('runs a custom tool through a sandbox', async () => {
        const COMPILED = `
            module.exports = {
                id: "echo",
                actions: { default: (args) => ({ echoed: args.x }) },
            }
        `
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        await bundle.write('rev1', 'tools/echo/compiled.js', COMPILED)
        await bundle.write(
            'rev1',
            'tools/echo/schema.json',
            JSON.stringify({ description: 'echo', args: { type: 'object' } })
        )
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 'sess1',
            teamId: 1,
            tools: [{ id: 'echo', compiledJs: COMPILED, schemaJson: {} }],
            nonces: {},
        })
        const pi = new MockPiClient([
            toolUseTurn([{ type: 'tool_use', id: 'tu_4', name: 'echo', input: { x: 42 } }]),
            endTurn('done'),
        ])
        const rev = makeRev({ tools: [{ kind: 'custom', id: 'echo', path: 'tools/echo/' }] })
        const out = await runSession(rev, makeSession(), {
            pi,
            bundle,
            sandbox,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        await pool.release('sess1')
    })

    it('propagates tool errors as is_error tool_result', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new MockPiClient([
            toolUseTurn([{ type: 'tool_use', id: 'tu_err', name: 'ghost-tool', input: {} }]),
            endTurn('ok recovered'),
        ])
        const rev = makeRev()
        const session = makeSession()
        await runSession(rev, session, { pi, bundle, sandbox: null, integrations: {}, secrets: {} })
        const userTurn = session.conversation[2] as { role: 'user'; content: unknown[] }
        expect((userTurn.content[0] as { is_error?: boolean }).is_error).toBe(true)
    })
})
