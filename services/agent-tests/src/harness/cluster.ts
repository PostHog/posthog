/**
 * `AgentCluster` — the e2e harness. Spawns `agent-ingress` and `agent-runner`
 * as **separate node subprocesses** (the same way they run in production) and
 * shares the local hogli stack between them: PostHog Postgres, the queue
 * Postgres, Kafka, Redis (for the SessionBus), ClickHouse, MinIO.
 *
 * Subprocesses, not in-process, because the agent-runner depends on the
 * Claude Agent SDK (ESM-only). A CJS module — anything jest loads — can't
 * `require()` an ESM module, so an in-process harness hits a hard
 * node-level wall the moment `AssServerExecutor` resolves. Spawning each
 * service as a fresh node process sidesteps the entire CJS/ESM ladder.
 *
 * Two lifecycle shapes:
 *
 *   1. `startCluster(opts)` — spawns its own ingress + runner, returns a
 *      handle that owns both. `cluster.stop()` SIGTERMs them. Used by
 *      tests that need an isolated cluster (e.g. a different executor).
 *
 *   2. `openSharedCluster()` — connects to bins spawned by the jest
 *      globalSetup, opens this-process pools, returns the same handle
 *      shape with a no-op `stop()`. The shared bins are torn down by
 *      globalTeardown. Mirrors production: one ingress + one runner
 *      serve every test app.
 */
import { type ChildProcess, spawn } from 'node:child_process'
import { createWriteStream, openSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'
import { Pool } from 'pg'

import {
    ApplicationsRepository,
    BundleStore,
    EncryptedFields,
    IdentitiesRepository,
    PosthogDbClient,
    SandboxInstancesRepository,
    SessionQueueManager,
    bundleStoreConfigFromEnv,
    loadDevEnv,
    logger,
} from '@posthog/agent-core'

import { ClickHouseClient } from './clickhouse'
import { CleanupRegistry } from './fixtures'
import { readSharedState } from './shared-state'

loadDevEnv()

const POSTHOG_DB_URL = process.env.POSTHOG_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
const QUEUE_DB_URL =
    process.env.AGENT_RUNTIME_QUEUE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
const KAFKA_BROKERS = process.env.KAFKA_HOSTS ?? 'localhost:9092'
const CLICKHOUSE_URL = process.env.CLICKHOUSE_HTTP_URL ?? 'http://localhost:8123'
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379/0'
const ENCRYPTION_SALT = '00beef0000beef0000beef0000beef00'

// Locate the built bins. Both services emit `dist/index.js` as their bin;
// we resolve relative to this file (the harness package's compiled output
// goes through ts-jest, but `__dirname` still points at the source path).
const INGRESS_BIN = resolvePath(__dirname, '../../../agent-ingress/dist/index.js')
const RUNNER_BIN = resolvePath(__dirname, '../../../agent-runner/dist/index.js')

export type ExecutorKind = 'echo' | 'principal-echo' | 'slow-cancellable' | 'failure' | 'sdk' | 'router'

export interface ClusterOptions {
    /**
     * Selects the runner's executor via `AGENT_RUNNER_TEST_EXECUTOR`.
     * Default `echo` — completes every session immediately and does NOT
     * touch the Claude SDK. App tests opt into `sdk` (real LLM) explicitly.
     */
    executor?: ExecutorKind
    /** In-memory secrets injected into the ingress + runner via JSON env. */
    secrets?: Record<string, string>
    /**
     * Extra env to pass into BOTH subprocesses. Useful for things like
     * `ANTHROPIC_API_KEY` (app tests) and `ANTHROPIC_MODEL`.
     */
    env?: Record<string, string>
}

export interface AgentCluster {
    readonly ingressUrl: string
    readonly port: number
    readonly posthog: Pool
    readonly queue: Pool
    readonly queueManager: SessionQueueManager
    readonly repository: ApplicationsRepository
    /** Same fernet keys the runner subprocess uses — for stamping encrypted_env from tests. */
    readonly encryption: EncryptedFields
    readonly identities: IdentitiesRepository
    readonly bundleStore: BundleStore
    readonly sandboxInstances: SandboxInstancesRepository
    readonly clickhouse: ClickHouseClient
    readonly cleanup: CleanupRegistry
    readonly internalSecret: string
    readonly internalHeader: string
    /** Stop subprocesses (SIGTERM, then waits up to 5s for exit). Drain pools. */
    stop(): Promise<void>
}

const INTERNAL_HEADER = 'x-posthog-internal'

export async function startCluster(opts: ClusterOptions = {}): Promise<AgentCluster> {
    const spawned = await spawnBins(opts)
    return openCluster(spawned)
}

interface SharedResources {
    spawned: SpawnedBins
    posthog: Pool
    queue: Pool
    queueManager: SessionQueueManager
    repository: ApplicationsRepository
    encryption: EncryptedFields
    identities: IdentitiesRepository
    bundleStore: BundleStore
    sandboxInstances: SandboxInstancesRepository
    clickhouse: ClickHouseClient
}

let sharedResources: SharedResources | null = null

/**
 * Connect to bins spawned by the jest globalSetup. Opens this-worker's
 * pools, ClickHouse client, etc. on first call and caches them — every
 * subsequent suite reuses the same connection pools. Each call still
 * returns a FRESH `CleanupRegistry` so suites don't step on each other's
 * teardown ordering when their afterAll runs.
 *
 * `stop()` is a no-op for the bins (globalTeardown owns those) and a
 * no-op for the pools (kept alive across suites; jest's `forceExit`
 * tears them down at end of run).
 */
export async function openSharedCluster(): Promise<AgentCluster> {
    if (!sharedResources) {
        sharedResources = await initSharedResources()
    }
    const r = sharedResources
    return {
        ingressUrl: r.spawned.ingressUrl,
        port: r.spawned.port,
        posthog: r.posthog,
        queue: r.queue,
        queueManager: r.queueManager,
        repository: r.repository,
        encryption: r.encryption,
        identities: r.identities,
        bundleStore: r.bundleStore,
        sandboxInstances: r.sandboxInstances,
        clickhouse: r.clickhouse,
        cleanup: new CleanupRegistry({ posthog: r.posthog, queue: r.queue }, r.encryption),
        internalSecret: r.spawned.internalSecret,
        internalHeader: INTERNAL_HEADER,
        stop: () => Promise.resolve(),
    }
}

async function initSharedResources(): Promise<SharedResources> {
    // `allowExitOnIdle: true` so jest's worker process drops cleanly after
    // the last test. Without it the pg pool's idle-connection timer keeps
    // the event loop alive and jest hangs forever waiting for "open
    // handles" to settle — historical workaround was `forceExit: true`,
    // which masks real leaks. This is the proper fix.
    const state = readSharedState()
    const posthog = new Pool({ connectionString: POSTHOG_DB_URL, allowExitOnIdle: true })
    const queue = new Pool({ connectionString: QUEUE_DB_URL, allowExitOnIdle: true })
    await probe(posthog, 'PostHog Postgres', POSTHOG_DB_URL)
    await probe(queue, 'queue Postgres', QUEUE_DB_URL)

    const clickhouse = new ClickHouseClient({ url: CLICKHOUSE_URL })
    await clickhouse.ping().catch((err) => {
        throw wrap(err, 'ClickHouse', CLICKHOUSE_URL)
    })

    const posthogDb = new PosthogDbClient({ dbUrl: POSTHOG_DB_URL, allowExitOnIdle: true })
    const encryption = new EncryptedFields(ENCRYPTION_SALT)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })
    const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })
    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())
    const queueManager = new SessionQueueManager({ pool: { dbUrl: QUEUE_DB_URL, allowExitOnIdle: true } })
    await queueManager.connect()

    return {
        spawned: {
            ingressUrl: state.ingressUrl,
            port: state.port,
            internalSecret: state.internalSecret,
            queueName: state.queueName,
            ingressProc: null,
            runnerProc: null,
        },
        posthog,
        queue,
        queueManager,
        repository,
        encryption,
        identities,
        bundleStore,
        sandboxInstances,
        clickhouse,
    }
}

export interface SpawnedBins {
    ingressUrl: string
    port: number
    internalSecret: string
    queueName: string
    /** When connected to externally-spawned bins (e.g. globalSetup), no child handle to manage. */
    ingressProc: ChildProcess | null
    runnerProc: ChildProcess | null
}

/**
 * Spawn ingress + runner subprocesses with the right env. Used by both
 * `startCluster()` (test-suite-local cluster) and the jest globalSetup
 * (shared cluster). Returns the child handles so the caller can manage
 * lifecycle.
 */
export interface SpawnBinsOptions extends ClusterOptions {
    /**
     * When set, redirect ingress/runner stdout+stderr to these files
     * instead of inheriting the parent's stdio. Used by globalSetup —
     * the bins outlive the jest test workers, so inheriting stdio would
     * dangle once the parent jest process exits.
     */
    logFiles?: { ingress: string; runner: string }
    /**
     * Optional override for the per-cluster internal secret / queue name.
     * Useful in tests that need stable values across reconnects (e.g. an
     * external supervisor). Random per cluster by default.
     */
    internalSecret?: string
    queueName?: string
}

export async function spawnBins(opts: SpawnBinsOptions = {}): Promise<SpawnedBins> {
    // Probe wires before paying the subprocess-spawn cost — clear hogli
    // pointer beats a cryptic mid-spawn failure.
    const probePool = new Pool({ connectionString: POSTHOG_DB_URL, max: 1 })
    try {
        await probe(probePool, 'PostHog Postgres', POSTHOG_DB_URL)
    } finally {
        await probePool.end()
    }

    const queueName = opts.queueName ?? `e2e-${Math.random().toString(36).slice(2, 10)}`
    const internalSecret = opts.internalSecret ?? `e2e-internal-${Math.random().toString(36).slice(2, 12)}`
    const port = await pickFreePort()
    const secrets = opts.secrets ?? {}

    const sharedEnv: NodeJS.ProcessEnv = {
        ...process.env,
        POSTHOG_DATABASE_URL: POSTHOG_DB_URL,
        AGENT_RUNTIME_QUEUE_DATABASE_URL: QUEUE_DB_URL,
        KAFKA_HOSTS: KAFKA_BROKERS,
        REDIS_URL,
        ENCRYPTION_SALT_KEYS: ENCRYPTION_SALT,
        AGENT_RUNNER_QUEUE_NAME: queueName,
        // Domain mode lets ingress route by `x-original-host`, the way the
        // existing tests + clients.ts already shape requests.
        SITE_URL: 'https://e2e.test',
        DOMAIN_SUFFIX: '.e2e.test',
        ROUTING_MODE: 'domain',
        // Tests don't need the resolver cache; force a fresh lookup per request.
        RESOLVER_TTL_MS: '0',
        ...opts.env,
    }

    const ingressEnv: NodeJS.ProcessEnv = {
        ...sharedEnv,
        PORT: String(port),
        AGENT_INGRESS_TEST_INTERNAL_SECRET: internalSecret,
        AGENT_INGRESS_TEST_SECRETS_JSON: JSON.stringify(secrets),
        AGENT_INGRESS_QUEUE_NAME: queueName,
    }
    const runnerEnv: NodeJS.ProcessEnv = {
        ...sharedEnv,
        AGENT_RUNNER_TEST_EXECUTOR: opts.executor ?? 'echo',
    }

    const ingressProc = spawnService('agent-ingress', INGRESS_BIN, ingressEnv, opts.logFiles?.ingress)
    const runnerProc = spawnService('agent-runner', RUNNER_BIN, runnerEnv, opts.logFiles?.runner)

    // Wait for ingress to bind. /health is unguarded; we just need a 2xx.
    const ingressUrl = `http://127.0.0.1:${port}`
    try {
        await waitForHealth(ingressUrl, { timeoutMs: 30_000 })
    } catch (err) {
        ingressProc.kill('SIGKILL')
        runnerProc.kill('SIGKILL')
        throw err
    }

    return { ingressUrl, port, internalSecret, queueName, ingressProc, runnerProc }
}

/**
 * Open this-process resources (pools, ClickHouse client, fixtures registry)
 * attached to the given bins. `stop()` SIGTERMs any owned child processes
 * and closes this-process pools — caller-owned bins (i.e. `ingressProc:
 * null`) are left alone for the external supervisor (globalTeardown) to
 * handle.
 */
async function openCluster(spawned: SpawnedBins): Promise<AgentCluster> {
    const posthog = new Pool({ connectionString: POSTHOG_DB_URL })
    const queue = new Pool({ connectionString: QUEUE_DB_URL })
    await probe(posthog, 'PostHog Postgres', POSTHOG_DB_URL)
    await probe(queue, 'queue Postgres', QUEUE_DB_URL)

    const clickhouse = new ClickHouseClient({ url: CLICKHOUSE_URL })
    await clickhouse.ping().catch((err) => {
        throw wrap(err, 'ClickHouse', CLICKHOUSE_URL)
    })

    const posthogDb = new PosthogDbClient({ dbUrl: POSTHOG_DB_URL })
    const encryption = new EncryptedFields(ENCRYPTION_SALT)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })
    const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })
    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())
    const queueManager = new SessionQueueManager({ pool: { dbUrl: QUEUE_DB_URL } })
    await queueManager.connect()

    const cleanup = new CleanupRegistry({ posthog, queue }, encryption)

    return {
        ingressUrl: spawned.ingressUrl,
        port: spawned.port,
        posthog,
        queue,
        queueManager,
        repository,
        encryption,
        identities,
        bundleStore,
        sandboxInstances,
        clickhouse,
        cleanup,
        internalSecret: spawned.internalSecret,
        internalHeader: INTERNAL_HEADER,
        async stop() {
            // External supervisor (globalTeardown) handles the bins when
            // these are null — only close this-process resources.
            if (spawned.ingressProc) {
                await terminate(spawned.ingressProc, 'agent-ingress')
            }
            if (spawned.runnerProc) {
                await terminate(spawned.runnerProc, 'agent-runner')
            }
            await queueManager.disconnect()
            await posthogDb.disconnect()
            await posthog.end()
            await queue.end()
        },
    }
}

/* ===== helpers ===== */

async function probe(pool: Pool, name: string, url: string): Promise<void> {
    try {
        await pool.query('SELECT 1')
    } catch (err) {
        throw wrap(err, name, url)
    }
}

function wrap(err: unknown, wire: string, target: string): Error {
    const msg = err instanceof Error ? err.message : String(err)
    return new Error(
        `agent-tests: ${wire} unreachable (${target}) — is hogli start running?\n  underlying error: ${msg}`
    )
}

/**
 * Spawn one of the bins under node. Inherits stderr to the parent so
 * runner / ingress logs are visible during a test run; stdout is piped
 * (and discarded) to keep jest's output clean.
 */
function spawnService(name: string, bin: string, env: NodeJS.ProcessEnv, logFile?: string): ChildProcess {
    // When logFile is set, stdout+stderr go to the file (used by
    // globalSetup — the bins outlive jest workers, so file-backed logs
    // are the only persistent way to inspect them).
    // Otherwise inherit stderr (genuine errors land in jest output); stdout
    // is gated on AGENT_TESTS_VERBOSE to avoid drowning the test report.
    const child = logFile
        ? (() => {
              // Truncate-on-open to keep dev tail-able and avoid append-bloat
              // across runs; the previous run's logs are gone.
              const fd = openSync(logFile, 'w')
              try {
                  const writer = createWriteStream(logFile, { flags: 'a', fd })
                  writer.write(`[${new Date().toISOString()}] ${name} spawned with PID …\n`)
              } catch {
                  /* logging is best-effort */
              }
              return spawn(process.execPath, [bin], {
                  env,
                  stdio: ['ignore', fd, fd],
              })
          })()
        : spawn(process.execPath, [bin], {
              env,
              stdio: ['ignore', process.env.AGENT_TESTS_VERBOSE ? 'inherit' : 'ignore', 'inherit'],
          })
    child.on('exit', (code, signal) => {
        if (code !== null && code !== 0) {
            logger.warn({ name, code, signal }, 'subprocess exited with non-zero code')
        }
    })
    return child
}

/**
 * Find a free TCP port the OS will hand back. Falls back to a high random
 * port if the probe fails — tests that try to bind it then get the same
 * EADDRINUSE error as production would.
 */
async function pickFreePort(): Promise<number> {
    const { createServer } = await import('node:net')
    return new Promise<number>((resolve, reject) => {
        const srv = createServer()
        srv.unref()
        srv.on('error', reject)
        srv.listen(0, '127.0.0.1', () => {
            const addr = srv.address()
            if (addr && typeof addr === 'object') {
                const port = addr.port
                srv.close(() => resolve(port))
            } else {
                reject(new Error('pickFreePort: address() returned a non-object'))
            }
        })
    })
}

/** Poll the ingress `/health` endpoint until it responds 200 or times out. */
async function waitForHealth(url: string, opts: { timeoutMs: number }): Promise<void> {
    const start = Date.now()
    while (Date.now() - start < opts.timeoutMs) {
        try {
            const res = await fetch(`${url}/health`)
            if (res.ok) {
                return
            }
        } catch {
            // not listening yet
        }
        await new Promise((r) => setTimeout(r, 100))
    }
    throw new Error(`agent-tests: ingress at ${url} did not come up within ${opts.timeoutMs}ms`)
}

/** SIGTERM the child; SIGKILL after 5s if it hasn't exited. */
async function terminate(child: ChildProcess, name: string): Promise<void> {
    if (child.exitCode !== null) {
        return
    }
    return new Promise<void>((resolve) => {
        const killTimer = setTimeout(() => {
            logger.warn(`${name}: forcing SIGKILL after grace period`)
            try {
                child.kill('SIGKILL')
            } catch {
                /* already dead */
            }
        }, 5_000)
        child.once('exit', () => {
            clearTimeout(killTimer)
            resolve()
        })
        try {
            child.kill('SIGTERM')
        } catch {
            clearTimeout(killTimer)
            resolve()
        }
    })
}
