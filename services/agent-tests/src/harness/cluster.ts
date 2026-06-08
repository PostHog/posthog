/**
 * In-process cluster harness for v2 e2e tests.
 *
 * Real everywhere except model invocation:
 *   - Postgres (agent_runtime_queue_test) — PgSessionQueue + PgRevisionStore.
 *     Schema is dropped + recreated per test.
 *   - SeaweedFS / S3 — `S3BundleStore` + `S3MemoryStore` against the
 *     `AGENT_MEMORY_TEST_S3_*` bucket, per-cluster random prefix. No fs/in-memory
 *     bundle store — every test exercises the real multipart write + signed-URL
 *     path that prod uses.
 *   - Redis (REDIS_URL, defaults to redis://localhost:6379) — RedisSessionEventBus
 *     with a per-cluster channel prefix so concurrent test files don't see each
 *     other's events. Same impl prod runs; in-memory bus has been removed.
 *   - Express ingress — full real route table.
 *   - Runner Worker — same loop the prod bin runs (concurrency, shutdown, pending_inputs).
 *   - Sandbox pool — InProcessSandboxPool (constructor refuses outside NODE_ENV=test).
 *   - Driver — streams through pi-ai's `streamSimple`, pointed at the faux provider.
 *
 * Mocked at the model layer ONLY: pi-ai's `faux` provider, registered once per
 * process. Each test sets its own scripted response list before firing the
 * trigger. Real-inference variants (gated by ANTHROPIC_API_KEY / etc.) skip the
 * faux setup and use a real provider Model — same harness, different model.
 */

import type { Model } from '@earendil-works/pi-ai'
import { createHmac } from 'crypto'
import { Express } from 'express'
import { Pool } from 'pg'
import request from 'supertest'

import { AuthProvider, buildApp, SessionEventBus, SlackSigningSecretResolver } from '@posthog/agent-ingress'
import { buildJanitorApp } from '@posthog/agent-janitor'
import { reset } from '@posthog/agent-migrations'
import { IntegrationHostValidator, IsAskerInApproverScope, McpTransportFactory, Worker } from '@posthog/agent-runner'
import type { IdentityStore, LogEntry } from '@posthog/agent-shared'
import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    buildTestBundleStore,
    buildTestStore as buildMemoryTestStore,
    CredentialBroker,
    InProcessSandboxPool,
    KafkaLogSink,
    newTestPrefix as newMemoryTestPrefix,
    PgApprovalStore,
    PgCredentialBroker,
    PgIdentityStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    RedisSessionEventBus,
    S3BundleStore,
    S3JsonlTabularStore,
    EncryptedFields,
    HttpClient,
    S3MemoryStore,
    SecretBroker,
    TEST_S3_BUCKET,
    wipeTestPrefix as wipeMemoryTestPrefix,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { buildFauxModel, ScriptedTurn } from './faux'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

/**
 * Test-side `LogSink`-shaped collector backed by `KafkaLogSink`. The real
 * sink does the produce; the tap accumulates entries for assertion. Tests
 * never query ClickHouse — the materialized view is async and flakey under
 * load. Validating that produce was called with the right wire bytes is the
 * contract that prevents drift; the downstream CH path is exercised in prod.
 */
export interface CollectingLogSink {
    readonly entries: LogEntry[]
    forSession(sessionId: string): LogEntry[]
    clear(): void
}

/** Deterministic 32-byte salt for the harness's `EncryptedFields`. Same key
 *  drives the credential broker and the Slack signing-secret resolver, so the
 *  encrypt/decrypt round-trip is exercised end-to-end on every test. */
const HARNESS_ENCRYPTION_SALT_KEYS = '01234567890123456789012345678901'

export interface BuildAgentInput {
    slug: string
    name?: string
    description?: string
    teamId?: number
    /** Spec input — accepts the partial shape before AgentSpecSchema applies defaults. */
    spec?: Record<string, unknown>
    files?: Record<string, string>
    /**
     * Plaintext env map. The harness Fernet-encrypts it with the same key the
     * harness's `SlackSigningSecretResolver` uses to decrypt, so production's
     * "decrypt at request time, look up key" path is exercised end-to-end.
     * Required for slack triggers (handler resolves `SLACK_SIGNING_SECRET_KEY`
     * here). Other triggers don't read env so this can stay undefined.
     */
    encrypted_env?: Record<string, string>
}

export interface Cluster {
    pool: Pool
    revisions: PgRevisionStore
    queue: PgSessionQueue
    bundle: S3BundleStore
    /** Per-cluster bucket prefix the bundle store is rooted at. */
    bundlePrefix: string
    bus: SessionEventBus
    identities: IdentityStore
    logs: CollectingLogSink
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
    /**
     * Real S3JsonlTabularStore (SeaweedFS in dev) wired through to ToolContext
     * for the `@posthog/table-*` tools. Shares the memory store's bucket prefix
     * so teardown wipes both at once.
     */
    tabularStore: S3JsonlTabularStore
    /** The faux pi-ai Model the runner is wired with. */
    model: Model<string>
    ingress: Express
    janitor: Express
    worker: Worker
    /** Compute the (timestamp, signature) Slack would send for `rawBody`
     *  using the caller-supplied signing secret. Convenience for tests that
     *  also pass that secret into `deployAgent` via `encrypted_env`. */
    signSlack(rawBody: string, secret: string): { ts: string; sig: string }
    /** Send a signed POST to `/agents/<slug>/slack/<action>` carrying `body`
     *  as JSON, signed with `secret`. Same secret must be set in the agent's
     *  `encrypted_env[SLACK_SIGNING_SECRET]`. */
    slackPost(slug: string, action: string, body: object, secret: string): Promise<import('supertest').Response>
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
    /**
     * Direct resolver override — used by tests that want to exercise the
     * per-agent `encrypted_env` lookup explicitly. Without this the harness
     * wires a resolver that returns `cluster.slackSigningSecret` for every
     * lookup, which is the right default for tests that just want a Slack
     * trigger to "work end-to-end" without populating an encrypted env.
     */
    slackSigningSecretResolver?: SlackSigningSecretResolver
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
    /**
     * Override the MCP transport factory. Defaults to the runner's own
     * `StreamableHTTPClientTransport`. Pair an in-process `McpServer` via
     * `InMemoryTransport.createLinkedPair()` here to drive `spec.mcps[]`
     * round-trips without binding a localhost port — see
     * `cases/mcp-tools.test.ts`.
     */
    mcpTransportFactory?: McpTransportFactory
    /**
     * Gates the `auth.integration` bearer attachment on `external` MCP refs.
     * Defaults to a permissive `() => true` so the common e2e cases don't
     * have to think about it; security-flavoured tests pass a stricter
     * implementation to exercise the rejection paths.
     */
    integrationHostValidator?: IntegrationHostValidator
    /**
     * Substitute the outbound HTTP client the runner threads into
     * `ToolContext.http`. Tests that want to assert on outbound headers
     * or short-circuit the network pass a `{ fetch: vi.fn(...) }` here.
     * Defaults to a real `HttpClient` with no proxy (direct fetch).
     */
    http?: import('@posthog/agent-shared').HttpFetcher
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

    // Real S3 bundle store against SeaweedFS, per-cluster prefix. Same impl
    // prod runs against real S3 — no fs/in-memory variant. The bucket and
    // client come from the shared `buildTestBundleStore` helper which mirrors
    // `buildTestStore` for the memory store.
    const bundlePrefix = `agent_bundles_harness_${Math.random().toString(36).slice(2, 10)}`
    const { client: bundleClient, store: bundle } = buildTestBundleStore(bundlePrefix)
    const revisions = new PgRevisionStore(pool)
    const queue = new PgSessionQueue(pool)
    // Real Redis pub/sub with a per-cluster channel prefix so concurrent test
    // files don't deliver each other's events. Same impl prod runs; in-memory
    // bus has been removed. Teardown disconnects.
    const busChannelPrefix = `harness_${Math.random().toString(36).slice(2, 10)}`
    const bus: SessionEventBus & { connect: () => Promise<void>; disconnect: () => Promise<void> } =
        new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: busChannelPrefix })
    await bus.connect()
    const identities: IdentityStore = new PgIdentityStore(pool)
    // Real KafkaLogSink against the local broker. The tap captures wire
    // payloads as they're produced so tests can assert on event shape
    // without polling ClickHouse. Teardown disconnects.
    const collected: LogEntry[] = []
    const logSink = new KafkaLogSink({
        brokers: KAFKA_HOSTS,
        topic: 'log_entries',
        name: 'agent_tests',
        tap: (entry) => collected.push(entry),
    })
    await logSink.connect()
    const logs: CollectingLogSink = {
        get entries(): LogEntry[] {
            return collected
        },
        forSession(sessionId: string): LogEntry[] {
            return collected.filter((e) => e.session_id === sessionId)
        },
        clear(): void {
            collected.length = 0
        },
    }
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
        encryptionSaltKeys: HARNESS_ENCRYPTION_SALT_KEYS,
    })
    // Real S3 (SeaweedFS) memory store with a per-cluster random prefix —
    // teardown wipes it. Failing here means SeaweedFS isn't up; fix the dev
    // stack rather than mocking around it.
    const memoryStorePrefix = newMemoryTestPrefix('agent_memory_harness')
    const { client: memoryStoreClient, store: memoryStore } = buildMemoryTestStore(memoryStorePrefix)
    // Tabular store shares the bucket + S3 client; the prefix scopes it under
    // the same harness root so teardown wipes both stores in one sweep.
    const tabularStore = new S3JsonlTabularStore({
        client: memoryStoreClient,
        bucket: TEST_S3_BUCKET,
        bucketPrefix: `${memoryStorePrefix}/tables`,
    })

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
        logs: logSink,
        resolveIntegrations: opts.resolveIntegrations ? async (s) => opts.resolveIntegrations!(s.id) : async () => ({}),
        resolveSecrets: opts.resolveSecrets ? async (s) => opts.resolveSecrets!(s.id) : async () => ({}),
        resolveModel: resolveModelForHarness,
        approvals,
        buildApprovalUrl: (requestId) => `/approvals/${requestId}`,
        isAskerInApproverScope: opts.isAskerInApproverScope,
        memoryStore,
        tabularStore,
        mcpTransportFactory: opts.mcpTransportFactory,
        // Permissive default so the common e2e suite doesn't have to know
        // about the security gate; the runtime-mcps cases that specifically
        // exercise integration auth (none in the suite yet) can override.
        integrationHostValidator: opts.integrationHostValidator ?? (() => true),
        maxConcurrency: 1, // tests prefer serial for deterministic state checks
        // Real HttpClient with no proxy by default — tests that exercise
        // outbound HTTP hit real localhost servers (matches the wider harness
        // stance of real-everywhere except the model layer). Tests that
        // want to assert on outbound headers / short-circuit the network
        // override via `BuildClusterOpts.http`.
        http: opts.http ?? new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
    })

    // Real-flow Slack signing secret resolver: decrypts the agent's
    // `encrypted_env` via the same `EncryptedFields` key the credential broker
    // uses, then plucks the requested key. Tests populate `encrypted_env` on
    // `deployAgent` to wire a secret per agent — same path production uses.
    const encryption = new EncryptedFields(HARNESS_ENCRYPTION_SALT_KEYS)
    const slackSigningSecretResolver: SlackSigningSecretResolver = opts.slackSigningSecretResolver ?? {
        async resolve(secretKey, application): Promise<string | null> {
            if (!application.encrypted_env) {
                return null
            }
            try {
                const env = encryption.decryptJsonEnv(application.encrypted_env)
                const value = env[secretKey]
                return typeof value === 'string' && value.length > 0 ? value : null
            } catch {
                return null
            }
        },
    }

    const ingress = buildApp({
        revisions,
        queue,
        bus,
        teamId,
        routingMode: opts.routingMode ?? 'path',
        pathPrefix: '/agents',
        domainSuffix: opts.domainSuffix,
        slackSigningSecretResolver,
        authProvider: opts.authProvider,
        identities,
        credentialBroker,
        // Same `http` the worker uses, so tests asserting on outbound
        // slack.com calls from the ingress (ack_reaction, identity bridge)
        // can route them through a single recorder.
        http: opts.http,
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
        bundlePrefix,
        bus,
        identities,
        sandboxInstances,
        logs,
        sandboxes,
        broker,
        credentialBroker,
        memoryStore,
        tabularStore,
        model,
        ingress,
        janitor,
        worker,
        signSlack(rawBody: string, secret: string): { ts: string; sig: string } {
            const ts = String(Math.floor(Date.now() / 1000))
            const mac = createHmac('sha256', secret).update(`v0:${ts}:${rawBody}`).digest('hex')
            return { ts, sig: `v0=${mac}` }
        },
        async slackPost(slug: string, action: string, body: object, secret: string): Promise<request.Response> {
            const raw = JSON.stringify(body)
            const ts = String(Math.floor(Date.now() / 1000))
            const mac = createHmac('sha256', secret).update(`v0:${ts}:${raw}`).digest('hex')
            return request(ingress)
                .post(`/agents/${slug}/slack/${action}`)
                .set('content-type', 'application/json')
                .set('x-slack-request-timestamp', ts)
                .set('x-slack-signature', `v0=${mac}`)
                .send(raw)
        },
        setScript(turns) {
            buildFauxModel(turns)
        },
        async deployAgent(input) {
            const tid = input.teamId ?? teamId
            // Fernet-encrypt the env map the same way Django would, so the
            // ingress's `SlackSigningSecretResolver` exercises real decrypt
            // → look-up at request time. Tests that don't pass `encrypted_env`
            // get null (matches an agent whose author never set any env).
            const encrypted_env = input.encrypted_env ? encryption.encrypt(JSON.stringify(input.encrypted_env)) : null
            const app = await revisions.createApplication({
                team_id: tid,
                slug: input.slug,
                name: input.name ?? input.slug,
                description: input.description ?? '',
                encrypted_env,
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
                // Test-side default: opt into public exposure so cases that
                // don't care about auth still get a working request flow
                // through the default PUBLIC_ONLY_AUTH_PROVIDER. The
                // runtime default (in AgentSpecSchema) is `posthog_internal`
                // — production specs that omit `auth` are closed by
                // default. We diverge here because the harness's
                // `PUBLIC_ONLY_AUTH_PROVIDER` can't verify anything else
                // without an explicit `fakeAuthProvider({...})` wired in.
                // Tests exercising real auth modes pass their own
                // `spec.auth` and override this.
                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                ...input.spec,
            })
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: `s3://${TEST_S3_BUCKET}/${bundlePrefix}/${app.id}/`,
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
            await wipeMemoryTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
            bundleClient.destroy()
            await wipeMemoryTestPrefix(memoryStoreClient, memoryStorePrefix).catch(() => undefined)
            memoryStoreClient.destroy()
            await bus.disconnect().catch(() => undefined)
            await logSink.disconnect().catch(() => undefined)
        },
    }
}
