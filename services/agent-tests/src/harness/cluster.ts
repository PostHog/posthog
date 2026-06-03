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
 *   - Driver — streams through pi-ai's `streamSimple`, pointed at the faux provider.
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

import { AuthProvider, buildApp, MemorySessionEventBus, SessionEventBus } from '@posthog/agent-ingress'
import { buildJanitorApp } from '@posthog/agent-janitor'
import { reset } from '@posthog/agent-migrations'
import { IsAskerInApproverScope, Worker } from '@posthog/agent-runner'
import type { IdentityStore } from '@posthog/agent-shared'
import { InMemoryLogSink, MemoryIdentityStore } from '@posthog/agent-shared'
import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    buildTestStore as buildMemoryTestStore,
    CredentialBroker,
    FsBundleStore,
    InProcessSandboxPool,
    newTestPrefix as newMemoryTestPrefix,
    PgApprovalStore,
    PgCredentialBroker,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    S3MemoryStore,
    SecretBroker,
    wipeTestPrefix as wipeMemoryTestPrefix,
} from '@posthog/agent-shared'
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
    credentialBroker: CredentialBroker
    sandboxInstances: PgSandboxInstanceStore
    broker: SecretBroker
    /**
     * Real S3MemoryStore (SeaweedFS in dev) wired through to ToolContext for the
     * `@posthog/memory-*` tools. Per-cluster random prefix isolates concurrent
     * tests; teardown wipes the prefix.
     */
    memoryStore: S3MemoryStore
    /** The faux pi-ai Model the runner is wired with. */
    model: Model<string>
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
    /**
     * Per-asker authorisation shortcut for approval-gated tools (#23
     * step 3). The harness doesn't carry a real
     * `posthog_organizationmembership` table, so tests stub the auth
     * decision directly — typically by inspecting the latest user-turn's
     * sender id. Omit to preserve B.2 v0 behaviour (every gated call
     * queues regardless of asker).
     */
    isAskerInApproverScope?: IsAskerInApproverScope
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

    // Single test DB holds both authoring (App, Revision — owned by Django
    // in prod) and runtime tables (Session, User, SandboxInstance — owned
    // by the worker). The production split happens at deploy time via two
    // pool URLs. reset() drops the public schema and reapplies every
    // migration from @posthog/agent-migrations — single source of truth.
    await reset({ databaseUrl: TEST_DB_URL })

    const bundleRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'v2-bundle-'))
    const bundle = new FsBundleStore(bundleRoot)
    const revisions = new PgRevisionStore(pool)
    const queue = new PgSessionQueue(pool)
    const bus: SessionEventBus = new MemorySessionEventBus()
    const identities: IdentityStore = new MemoryIdentityStore()
    const logs = new InMemoryLogSink()
    const sandboxes = new InProcessSandboxPool()
    const sandboxInstances = new PgSandboxInstanceStore(pool)
    const approvals = new PgApprovalStore(pool)
    const broker = new SecretBroker()
    // Real PG-backed credential broker — matches what prod runs. Mocking
    // this with an in-memory map would let test-only behavior diverge
    // from the real SQL path (per the harness CLAUDE.md "no fakes for
    // the persistence layer" rule).
    // Deterministic per-cluster key — encryption is the real path even
    // in tests so the encrypt/decrypt round-trip is exercised.
    // EncryptedFields expects a 32-byte UTF-8 string (same constraint
    // production uses; matches `pg-impls.test.ts`).
    const credentialBroker = new PgCredentialBroker(pool, {
        encryptionSaltKeys: '01234567890123456789012345678901',
    })
    // Real S3 (SeaweedFS) memory store with a per-cluster random prefix —
    // teardown wipes it. Failing here means SeaweedFS isn't up; fix the dev
    // stack rather than mocking around it.
    const memoryStorePrefix = newMemoryTestPrefix('agent_memory_harness')
    const { client: memoryStoreClient, store: memoryStore } = buildMemoryTestStore(memoryStorePrefix)

    const model = opts.model ?? buildFauxModel(opts.initialScript ?? [])
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
        sandboxInstances,
        broker,
        credentialBroker,
        bus,
        logs,
        resolveIntegrations: opts.resolveIntegrations ? async (s) => opts.resolveIntegrations!(s.id) : async () => ({}),
        resolveSecrets: opts.resolveSecrets ? async (s) => opts.resolveSecrets!(s.id) : async () => ({}),
        resolveModel: resolveModelForHarness,
        approvals,
        buildApprovalUrl: (requestId) => `/approvals/${requestId}`,
        isAskerInApproverScope: opts.isAskerInApproverScope,
        memoryStore,
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
        credentialBroker,
    })

    const janitor = buildJanitorApp({
        queue,
        approvals,
        revisions,
        bundles: bundle,
        sweep: { queue, approvals, stuckRunningThresholdMs: 60_000 },
        // Shared with the worker — same bucket, same prefix. Memory routes
        // (/memory/team/:t/agent/:a/...) read + write through this store and
        // the runner's `@posthog/memory-*` tools hit the same files.
        memoryStore,
    })

    return {
        pool,
        revisions,
        queue,
        bundle,
        bundleRoot,
        bus,
        identities,
        sandboxInstances,
        logs,
        sandboxes,
        broker,
        credentialBroker,
        memoryStore,
        model,
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
                created_by_id: null,
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
            await wipeMemoryTestPrefix(memoryStoreClient, memoryStorePrefix).catch(() => undefined)
            memoryStoreClient.destroy()
        },
    }
}
