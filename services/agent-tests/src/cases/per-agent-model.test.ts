/**
 * Per-agent spec.model: two agents in the same cluster declare different
 * spec.model strings. The runner resolves each through `resolveModel`, and the
 * resolved Model is what the driver streams with.
 *
 * `resolveModel` is the routing seam (called once per session in the worker),
 * so we record there and back it with the faux provider so each session
 * actually runs to completion.
 */

import { type AssistantMessage, fauxAssistantMessage, type Model, registerFauxProvider } from '@earendil-works/pi-ai'
import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'
import { Pool } from 'pg'

import { reset } from '@posthog/agent-migrations'
import { Worker } from '@posthog/agent-runner'
import {
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    FsBundleStore,
    HttpClient,
    InProcessSandboxPool,
    PgRevisionStore,
    PgSessionQueue,
    SecretBroker,
} from '@posthog/agent-shared'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

let fauxHandle: ReturnType<typeof registerFauxProvider> | undefined

/**
 * Return a Model whose id is the spec string but whose `api` routes to the faux
 * provider, armed with a single completing response so the session finishes.
 */
function fauxModelFor(specModel: string): Model<string> {
    if (!fauxHandle) {
        fauxHandle = registerFauxProvider({ api: 'faux', provider: 'faux', models: [{ id: 'faux' }] })
    }
    fauxHandle.setResponses([fauxAssistantMessage(`from ${specModel}`, { stopReason: 'stop' }) as AssistantMessage])
    return { id: specModel, name: specModel, api: 'faux', provider: 'faux' } as unknown as Model<string>
}

describe('per-agent spec.model resolution: real e2e', () => {
    let pool: Pool
    let bundleRoot: string

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        bundleRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'permodel-'))
    })

    afterEach(async () => {
        await fs.rm(bundleRoot, { recursive: true, force: true }).catch(() => undefined)
    })

    afterAll(async () => {
        await pool.end()
    })

    it('two agents with different spec.model values resolve distinct Models', async () => {
        const bundle = new FsBundleStore(bundleRoot)
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const modelsResolved: string[] = []

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            // Per-agent model resolution — keys off spec.model verbatim. This is
            // the seam the driver streams with, so recording here proves routing.
            resolveModel: (specModel) => {
                modelsResolved.push(specModel)
                return fauxModelFor(specModel)
            },
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
                idempotency_key: null,
                trigger_metadata: null,
                state: 'queued',
                conversation: [{ role: 'user', content: 'go', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                acl: [],
                pending_elevation_requests: [],
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            })
        }

        await worker.loop({ iterations: 2, claimTimeoutMs: 10 })

        // Both models should have been resolved exactly once each.
        expect(modelsResolved.sort()).toEqual(['faux/model-A', 'faux/model-B'])
    })
})
