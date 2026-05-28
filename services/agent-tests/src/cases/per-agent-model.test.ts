/**
 * Per-agent spec.model: two agents in the same cluster declare different
 * spec.model strings. The runner resolves each through `resolveModel` and the
 * PiClient receives a different Model per session.
 *
 * Exercised via a custom resolveModel that returns distinct Model objects per
 * input string, plus a FauxPiClient subclass that records which model each
 * invocation used.
 */

import type { AssistantMessage, Context, Model } from '@earendil-works/pi-ai'
import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'
import { Pool } from 'pg'

import { FauxPiClient, InvokeOpts, Worker } from '@posthog/agent-runner'
import {
    AgentSpecSchema,
    FsBundleStore,
    InProcessSandboxPool,
    PgRevisionStore,
    PgSessionQueue,
    SecretBroker,
    DROP_SQL,
    SCHEMA_SQL,
} from '@posthog/agent-shared'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

function stubModel(id: string): Model<string> {
    return { id, name: id, api: 'faux', provider: 'stub' } as unknown as Model<string>
}

class RecordingPi extends FauxPiClient {
    public readonly modelsCalled: string[] = []
    constructor() {
        super([])
    }
    override async invoke(model: Model<string>, _context: Context, _opts?: InvokeOpts): Promise<AssistantMessage> {
        this.modelsCalled.push(model.id)
        return {
            role: 'assistant',
            content: [{ type: 'text', text: `from ${model.id}` }],
            stopReason: 'stop',
            timestamp: Date.now(),
            api: 'faux',
            provider: 'stub',
            model: model.id,
            usage: {
                input: 0,
                output: 0,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 0,
                cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
            },
        }
    }
}

describe('per-agent spec.model resolution: real e2e', () => {
    let pool: Pool
    let bundleRoot: string

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
    })

    beforeEach(async () => {
        await pool.query(DROP_SQL)
        await pool.query(SCHEMA_SQL)
        bundleRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'permodel-'))
    })

    afterEach(async () => {
        await fs.rm(bundleRoot, { recursive: true, force: true }).catch(() => undefined)
    })

    afterAll(async () => {
        await pool.end()
    })

    it('two agents with different spec.model values invoke distinct Model objects', async () => {
        const bundle = new FsBundleStore(bundleRoot)
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const recordingPi = new RecordingPi()

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: recordingPi,
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            // Per-agent model resolution — keys off spec.model verbatim.
            resolveModel: (specModel) => stubModel(specModel),
            maxConcurrency: 1,
        })

        // Two agents with distinct spec.model strings.
        for (const [slug, model] of [
            ['agent-a', 'faux/model-A'],
            ['agent-b', 'faux/model-B'],
        ] as const) {
            const app = await revisions.createApplication({ team_id: 1, slug, name: slug, description: '' })
            const spec = AgentSpecSchema.parse({ model, triggers: [{ type: 'chat', config: { require_auth: false } }] })
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: `fs://${bundleRoot}/${app.id}/`,
                spec,
            })
            await bundle.write(rev.id, 'agent.md', 'x')
            const sha = await bundle.freeze(rev.id)
            await revisions.setRevisionState(rev.id, 'ready', sha)
            await revisions.setRevisionState(rev.id, 'live', sha)
            await revisions.setLiveRevision(app.id, rev.id)

            // Enqueue a session for this agent.
            await queue.enqueue({
                id: `00000000-0000-0000-0000-0000000000${slug === 'agent-a' ? 'a1' : 'b2'}`,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                conversation: [{ role: 'user', content: 'go', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            })
        }

        await worker.loop({ iterations: 2, claimTimeoutMs: 10 })

        // Both models should have been invoked exactly once each.
        expect(recordingPi.modelsCalled.sort()).toEqual(['faux/model-A', 'faux/model-B'])
    })
})
