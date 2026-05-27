import {
    AgentSession,
    AgentSpecSchema,
    InProcessSandboxPool,
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
    SecretBroker,
} from '@posthog/agent-shared-v2'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { endTurn, MockPiClient, toolUseTurn } from './pi-client'
import { Worker } from './worker'

describe('Worker', () => {
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

    it('claims a session, runs it, marks it completed', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'claude-opus-4-7' }),
        })
        await bundle.write(rev.id, 'agent.md', 'you are a bot')

        const session: AgentSession = {
            id: 'sess1',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hello' }],
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new MockPiClient([endTurn('hi back')]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess1')
        expect(after!.state).toBe('completed')
    })

    it('session with custom tool acquires + releases the sandbox', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const COMPILED = `
            module.exports = {
                id: "noop",
                actions: { default: () => ({ ok: true }) },
            }
        `

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'x',
                tools: [{ kind: 'custom', id: 'noop', path: 'tools/noop/' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        await bundle.write(rev.id, 'tools/noop/compiled.js', COMPILED)
        await bundle.write(rev.id, 'tools/noop/schema.json', JSON.stringify({ description: 'noop' }))

        const session: AgentSession = {
            id: 'sess2',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi' }],
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const pool = new InProcessSandboxPool()
        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: pool,
            pi: new MockPiClient([
                toolUseTurn([{ type: 'tool_use', id: 'x', name: 'noop', input: {} }]),
                endTurn('done'),
            ]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({ ACME_KEY: 'topsecret' }),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess2')
        expect(after!.state).toBe('completed')
    })
})
