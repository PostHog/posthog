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
 * Lifecycle:
 *   - `startCluster(opts)` connects pools, spawns ingress + runner, polls
 *     ingress `/health` until ready, returns the handle.
 *   - `cluster.stop()` — SIGTERM both subprocesses, wait for clean exits,
 *     drain pools.
 *
 * Tests own their cluster (one per suite). Fixtures register teardown on
 * `cluster.cleanup`; `afterAll` runs cleanup then stop.
 */
import { type ChildProcess, spawn } from 'node:child_process'
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

export type ExecutorKind = 'echo' | 'principal-echo' | 'sdk'

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
    // 1. Probe every wire fast — clear hogli pointer beats a cryptic mid-test failure.
    const posthog = new Pool({ connectionString: POSTHOG_DB_URL })
    const queue = new Pool({ connectionString: QUEUE_DB_URL })
    await probe(posthog, 'PostHog Postgres', POSTHOG_DB_URL)
    await probe(queue, 'queue Postgres', QUEUE_DB_URL)

    const clickhouse = new ClickHouseClient({ url: CLICKHOUSE_URL })
    await clickhouse.ping().catch((err) => {
        throw wrap(err, 'ClickHouse', CLICKHOUSE_URL)
    })

    // 2. Harness-side deps for fixtures + assertions (NOT shared with the
    //    subprocesses — those construct their own from the env we pass).
    const posthogDb = new PosthogDbClient({ dbUrl: POSTHOG_DB_URL })
    const encryption = new EncryptedFields(ENCRYPTION_SALT)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })
    const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })
    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())
    const queueManager = new SessionQueueManager({ pool: { dbUrl: QUEUE_DB_URL } })
    await queueManager.connect()

    // 3. Per-cluster knobs — random per run, plumbed into both subprocesses.
    const queueName = `e2e-${Math.random().toString(36).slice(2, 10)}`
    const internalSecret = `e2e-internal-${Math.random().toString(36).slice(2, 12)}`
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
    }
    const runnerEnv: NodeJS.ProcessEnv = {
        ...sharedEnv,
        AGENT_RUNNER_TEST_EXECUTOR: opts.executor ?? 'echo',
        // The runner's stub executors don't need a key; the sdk executor does.
        // Caller threads ANTHROPIC_API_KEY through opts.env in that case.
    }
    // Ingress doesn't enqueue with a `queueName` override yet via env. We
    // wire it indirectly: ingress reads the queue name from a dedicated
    // env (added below), passes it via createIngress(overrides.queueName).
    ingressEnv.AGENT_INGRESS_QUEUE_NAME = queueName

    const ingressProc = spawnService('agent-ingress', INGRESS_BIN, ingressEnv)
    const runnerProc = spawnService('agent-runner', RUNNER_BIN, runnerEnv)

    // 4. Wait for ingress to bind. /health is unguarded; we just need a 2xx.
    const ingressUrl = `http://127.0.0.1:${port}`
    try {
        await waitForHealth(ingressUrl, { timeoutMs: 30_000 })
    } catch (err) {
        ingressProc.kill('SIGKILL')
        runnerProc.kill('SIGKILL')
        throw err
    }

    const cleanup = new CleanupRegistry({ posthog, queue })

    return {
        ingressUrl,
        port,
        posthog,
        queue,
        queueManager,
        repository,
        identities,
        bundleStore,
        sandboxInstances,
        clickhouse,
        cleanup,
        internalSecret,
        internalHeader: INTERNAL_HEADER,
        async stop() {
            await terminate(ingressProc, 'agent-ingress')
            await terminate(runnerProc, 'agent-runner')
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
function spawnService(name: string, bin: string, env: NodeJS.ProcessEnv): ChildProcess {
    const child = spawn(process.execPath, [bin], {
        env,
        // stdout → ignore (chatty pino logs); stderr → inherit so genuine
        // errors land in the jest output.
        stdio: ['ignore', 'ignore', 'inherit'],
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
