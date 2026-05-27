/**
 * In-process cluster harness for v2 e2e tests.
 *
 * Real:
 *   - Postgres (agent_runtime_queue_test) — PgSessionQueue + PgRevisionStore.
 *     Schema is created fresh per suite, tables truncated per test.
 *   - Filesystem — FsBundleStore in a per-suite tmp dir.
 *   - Express ingress — full real route table.
 *   - Runner Worker — same loop the prod bin runs.
 *   - Sandbox pool — InProcessSandboxPool (zero-isolation, fast).
 *   - HttpPiClient hitting a real HTTP server we control (mock-pi-dev).
 *
 * Mocked (HTTP level only):
 *   - mock-pi-dev — model API. Built-in models (mock-echo, mock-static:…,
 *     mock-tool:…, mock-ask, mock-end, mock-loop, mock-error:…) cover most
 *     test needs. Real inference proxies via `proxyUpstream` when configured.
 *
 * Everything else runs the real code path.
 */

import { Express } from 'express'
import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'
import { Pool } from 'pg'

import { AuthProvider, buildApp, MemorySessionEventBus, SessionEventBus } from '@posthog/agent-ingress-v2'
import { buildJanitorApp } from '@posthog/agent-janitor-v2'
import { HttpPiClient, Worker } from '@posthog/agent-runner-v2'
import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    DROP_SQL,
    FsBundleStore,
    InProcessSandboxPool,
    PgRevisionStore,
    PgSessionQueue,
    SCHEMA_SQL,
    SecretBroker,
} from '@posthog/agent-shared-v2'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { MockPiHandle, startMockPi } from './mock-pi-dev'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const PROXY_UPSTREAM = process.env.PI_DEV_BASE_URL // when set, mock proxies real inference
const PROXY_API_KEY = process.env.PI_DEV_API_KEY

export interface BuildAgentInput {
    slug: string
    name?: string
    description?: string
    teamId?: number
    /** Spec input — accepts the partial shape before AgentSpecSchema applies defaults. */
    spec?: Record<string, unknown>
    files?: Record<string, string>
}

export interface Cluster {
    pool: Pool
    revisions: PgRevisionStore
    queue: PgSessionQueue
    bundle: FsBundleStore
    bundleRoot: string
    bus: SessionEventBus
    sandboxes: InProcessSandboxPool
    broker: SecretBroker
    pi: MockPiHandle
    piClient: HttpPiClient
    ingress: Express
    janitor: Express
    worker: Worker
    deployAgent(input: BuildAgentInput): Promise<{ application: AgentApplication; revision: AgentRevision }>
    /** Pump the runner. Default: drain queue (up to 50 iterations). */
    drain(opts?: { iterations?: number }): Promise<void>
    /** Clean up resources. Idempotent. */
    teardown(): Promise<void>
}

export interface BuildClusterOpts {
    teamId?: number
    routingMode?: 'path' | 'domain'
    domainSuffix?: string
    slackSigningSecret?: string
    /** Override the per-session secret resolver (defaults to empty). */
    resolveSecrets?: (sessionId: string) => Promise<Record<string, string>>
    /** Override the per-session integrations resolver (defaults to empty). */
    resolveIntegrations?: (
        sessionId: string
    ) => Promise<Record<string, { kind: string; access_token: string; refresh_token?: string }>>
    authProvider?: AuthProvider
}

let _pool: Pool | null = null

async function getPool(): Promise<Pool> {
    if (_pool) {
        return _pool
    }
    _pool = new Pool({ connectionString: TEST_DB_URL, max: 8 })
    await _pool.query('SELECT 1') // probe
    return _pool
}

export async function closeSharedPool(): Promise<void> {
    if (_pool) {
        await _pool.end()
        _pool = null
    }
}

export async function buildCluster(opts: BuildClusterOpts = {}): Promise<Cluster> {
    const teamId = opts.teamId ?? 1
    const pool = await getPool()

    // Fresh schema per test — drop and recreate.
    await pool.query(DROP_SQL)
    await pool.query(SCHEMA_SQL)

    const bundleRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'v2-bundle-'))
    const bundle = new FsBundleStore(bundleRoot)
    const revisions = new PgRevisionStore(pool)
    const queue = new PgSessionQueue(pool)
    const bus: SessionEventBus = new MemorySessionEventBus()
    const sandboxes = new InProcessSandboxPool()
    const broker = new SecretBroker()

    const pi = await startMockPi({
        proxyUpstream: PROXY_UPSTREAM,
        proxyApiKey: PROXY_API_KEY,
    })
    const piClient = new HttpPiClient({
        baseUrl: pi.baseUrl,
        apiKey: process.env.AGENT_TEST_PI_API_KEY ?? 'test-key',
    })

    // For native posthog.query.v1 etc. tests use the in-process echo client.
    setPosthogInternalClient({
        async runHogql({ query }) {
            return { rows: [{ query }], columns: ['query'] }
        },
        async searchPersons() {
            return { persons: [] }
        },
    })

    const worker = new Worker({
        queue,
        revisions,
        bundle,
        sandboxes,
        pi: piClient,
        broker,
        resolveIntegrations: opts.resolveIntegrations ? async (s) => opts.resolveIntegrations!(s.id) : async () => ({}),
        resolveSecrets: opts.resolveSecrets ? async (s) => opts.resolveSecrets!(s.id) : async () => ({}),
    })

    const ingress = buildApp({
        revisions,
        queue,
        bus,
        teamId,
        routingMode: opts.routingMode ?? 'path',
        pathPrefix: '/agents',
        domainSuffix: opts.domainSuffix,
        slackSigningSecret: opts.slackSigningSecret,
        authProvider: opts.authProvider,
    })

    const janitor = buildJanitorApp({
        queue,
        sweep: { queue, stuckThresholdMs: 60_000, listCandidates: async () => [] },
    })

    return {
        pool,
        revisions,
        queue,
        bundle,
        bundleRoot,
        bus,
        sandboxes,
        broker,
        pi,
        piClient,
        ingress,
        janitor,
        worker,
        async deployAgent(input) {
            const tid = input.teamId ?? teamId
            const app = await revisions.createApplication({
                team_id: tid,
                slug: input.slug,
                name: input.name ?? input.slug,
                description: input.description ?? '',
            })
            // Default: every trigger enabled. Tests that want trigger gating
            // pass `spec.triggers` explicitly to restrict.
            const spec = AgentSpecSchema.parse({
                model: 'mock-echo',
                triggers: [
                    { type: 'chat', config: { require_auth: false } },
                    { type: 'slack', config: {} },
                    { type: 'webhook', config: { path: '/webhook' } },
                    { type: 'mcp', config: {} },
                ],
                ...input.spec,
            })
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by: 'harness',
                bundle_uri: `fs://${bundleRoot}/${app.id}/`,
                spec,
            })
            for (const [p, content] of Object.entries(input.files ?? {})) {
                await bundle.write(rev.id, p, content)
            }
            if (!input.files?.['agent.md']) {
                await bundle.write(rev.id, 'agent.md', 'You are a test agent.')
            }
            const sha = await bundle.freeze(rev.id)
            await revisions.setRevisionState(rev.id, 'ready', sha)
            await revisions.setRevisionState(rev.id, 'live', sha)
            await revisions.setLiveRevision(app.id, rev.id)
            const refreshedApp = await revisions.getApplication(app.id)
            const refreshedRev = await revisions.getRevision(rev.id)
            return { application: refreshedApp!, revision: refreshedRev! }
        },
        async drain(o) {
            // Quick-drain: each iteration tries to claim with a tiny timeout; if
            // we get N consecutive empties, the queue is drained.
            const maxIterations = o?.iterations ?? 50
            const maxEmpty = 3
            let empty = 0
            let i = 0
            while (i < maxIterations && empty < maxEmpty) {
                const session = await queue.claim(10)
                if (!session) {
                    empty++
                    await new Promise((r) => setTimeout(r, 20))
                    continue
                }
                empty = 0
                await worker.runOne(session)
                i++
            }
        },
        async teardown() {
            await pi.close().catch(() => undefined)
            await fs.rm(bundleRoot, { recursive: true, force: true }).catch(() => undefined)
        },
    }
}
