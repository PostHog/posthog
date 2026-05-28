/**
 * In-process cluster harness for v2 e2e tests.
 *
 * Real everywhere except model invocation:
 *   - Postgres (agent_runtime_queue_test) — PgSessionQueue + PgRevisionStore.
 *     Schema is dropped + recreated per test.
 *   - Filesystem — FsBundleStore in a per-test tmp dir.
 *   - Express ingress — full real route table.
 *   - Runner Worker — same loop the prod bin runs (concurrency, shutdown, pending_inputs).
 *   - Sandbox pool — InProcessSandboxPool.
 *   - PiAiClient — the real production client, pointed at pi-ai's faux provider.
 *
 * Mocked at the model layer ONLY: pi-ai's `faux` provider, registered once per
 * process. Each test sets its own scripted response list before firing the
 * trigger. Real-inference variants (gated by ANTHROPIC_API_KEY / etc.) skip the
 * faux setup and use a real provider Model — same harness, different model.
 */

import type { Model } from '@earendil-works/pi-ai'
import { Express } from 'express'
import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'
import { Pool } from 'pg'

import { AuthProvider, buildApp, MemorySessionEventBus, SessionEventBus } from '@posthog/agent-ingress-v2'
import { buildJanitorApp } from '@posthog/agent-janitor-v2'
import { PiAiClient, Worker } from '@posthog/agent-runner-v2'
import type { IdentityStore } from '@posthog/agent-shared-v2'
import { InMemoryLogSink, MemoryIdentityStore } from '@posthog/agent-shared-v2'
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

import { buildFauxModel, ScriptedTurn } from './faux'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

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
    identities: IdentityStore
    logs: InMemoryLogSink
    sandboxes: InProcessSandboxPool
    broker: SecretBroker
    /** The faux pi-ai Model the runner is wired with. */
    model: Model<string>
    piClient: PiAiClient
    ingress: Express
    janitor: Express
    worker: Worker
    /** Rearm the faux provider's response script for the next pi-ai call(s). */
    setScript(turns: ScriptedTurn[]): void
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
    /**
     * Optional initial script for the faux provider. Tests that script per-test
     * call `cluster.setScript(...)` before firing triggers.
     */
    initialScript?: ScriptedTurn[]
    /**
     * Override the model — set this to a real provider Model (e.g.
     * `getModel('anthropic', 'claude-sonnet-4-7')`) for real-inference tests.
     */
    model?: Model<string>
}

let _pool: Pool | null = null

async function getPool(): Promise<Pool> {
    if (_pool) {
        return _pool
    }
    _pool = new Pool({ connectionString: TEST_DB_URL, max: 8 })
    await _pool.query('SELECT 1')
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

    await pool.query(DROP_SQL)
    await pool.query(SCHEMA_SQL)

    const bundleRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'v2-bundle-'))
    const bundle = new FsBundleStore(bundleRoot)
    const revisions = new PgRevisionStore(pool)
    const queue = new PgSessionQueue(pool)
    const bus: SessionEventBus = new MemorySessionEventBus()
    const identities: IdentityStore = new MemoryIdentityStore()
    const logs = new InMemoryLogSink()
    const sandboxes = new InProcessSandboxPool()
    const broker = new SecretBroker()

    const model = opts.model ?? buildFauxModel(opts.initialScript ?? [])
    const piClient = new PiAiClient(process.env.AGENT_TEST_API_KEY ?? 'faux-key')
    // resolveModel ignores spec.model and always returns the harness's Model —
    // tests don't exercise per-agent model selection (that's covered in
    // real-inference + dedicated tests).
    const resolveModelForHarness = (): typeof model => model

    // For native @posthog/query etc. tests use the in-process echo client.
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
        bus,
        logs,
        resolveIntegrations: opts.resolveIntegrations ? async (s) => opts.resolveIntegrations!(s.id) : async () => ({}),
        resolveSecrets: opts.resolveSecrets ? async (s) => opts.resolveSecrets!(s.id) : async () => ({}),
        resolveModel: resolveModelForHarness,
        maxConcurrency: 1, // tests prefer serial for deterministic state checks
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
        identities,
    })

    const janitor = buildJanitorApp({
        queue,
        sweep: { queue, stuckRunningThresholdMs: 60_000 },
    })

    return {
        pool,
        revisions,
        queue,
        bundle,
        bundleRoot,
        bus,
        identities,
        logs,
        sandboxes,
        broker,
        model,
        piClient,
        ingress,
        janitor,
        worker,
        setScript(turns) {
            buildFauxModel(turns)
        },
        async deployAgent(input) {
            const tid = input.teamId ?? teamId
            const app = await revisions.createApplication({
                team_id: tid,
                slug: input.slug,
                name: input.name ?? input.slug,
                description: input.description ?? '',
            })
            const spec = AgentSpecSchema.parse({
                // Default model is "faux/<name>"; tests can override via spec.model.
                model: 'faux/faux',
                triggers: [
                    { type: 'chat', config: { require_auth: false } },
                    // Default to "*" for tests — individual cases override
                    // with explicit trusted_workspaces to exercise the gate.
                    { type: 'slack', config: { trusted_workspaces: '*' } },
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
            await fs.rm(bundleRoot, { recursive: true, force: true }).catch(() => undefined)
        },
    }
}
