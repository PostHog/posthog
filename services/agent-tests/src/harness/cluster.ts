import { Pool } from 'pg'

/**
 * `AgentCluster` — the e2e harness. Boots agent-ingress + agent-runner in
 * the same Node process by calling the same `createIngress` / `createRunner`
 * factories the production bins use. Shares pools, bus, and log producer
 * between the two so they exchange events in-process and write to the local
 * Kafka + ClickHouse the way they would in prod.
 *
 * Lifecycle:
 *   - `startCluster(opts)` — creates shared deps, builds ingress + runner,
 *     starts both, returns the cluster handle. Throws with a hogli hint if
 *     any wire is unreachable.
 *   - `cluster.stop()` — graceful: runner first (drain in-flight), then
 *     factory stop calls, then shared deps the harness owns.
 */
import {
    ApplicationsRepository,
    EncryptedFields,
    IdentitiesRepository,
    InMemorySessionBus,
    KafkaLogProducer,
    PosthogDbClient,
    type SessionBus,
    SessionQueueManager,
} from '@posthog/agent-core'
import { type Ingress, type ServerDeps, createIngress } from '@posthog/agent-ingress'
import { type Runner, type SessionExecutor, createRunner } from '@posthog/agent-runner'

import { ClickHouseClient } from './clickhouse'
import { CleanupRegistry } from './fixtures'

const POSTHOG_DB_URL = process.env.POSTHOG_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
const QUEUE_DB_URL =
    process.env.AGENT_RUNTIME_QUEUE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
const KAFKA_BROKERS = process.env.KAFKA_HOSTS ?? 'localhost:9092'
const CLICKHOUSE_URL = process.env.CLICKHOUSE_HTTP_URL ?? 'http://localhost:8123'
const ENCRYPTION_SALT = '00beef0000beef0000beef0000beef00'
const LOG_ENTRIES_TOPIC = process.env.KAFKA_LOG_ENTRIES_TOPIC ?? 'log_entries'

export interface ClusterOptions {
    /** Replace the runner's executor (default: `EchoExecutor`). Tests use `PrincipalEchoExecutor`. */
    executor?: SessionExecutor
    /** Override `verifyPostHogInternal` (default: accept the test internal header). */
    verifyPostHogInternal?: ServerDeps['verifyPostHogInternal']
    /** In-memory secrets keyed by name. The harness's `loadSecret` returns from here. */
    secrets?: Record<string, string>
}

export interface AgentCluster {
    readonly ingressUrl: string
    readonly port: number
    /** Raw `pg` pool for assertions / cleanup. */
    readonly posthog: Pool
    readonly queue: Pool
    /** Shared queue manager — same instance ingress and runner both use. */
    readonly queueManager: SessionQueueManager
    /** Shared bus — ingress publishes, runner subscribes, all in-process. */
    readonly bus: SessionBus
    /** HTTP client for ClickHouse log_entries assertions. */
    readonly clickhouse: ClickHouseClient
    /** Fixture cleanup tracker. */
    readonly cleanup: CleanupRegistry
    /** Test internal-header secret accepted by the default verifier. */
    readonly internalSecret: string
    readonly internalHeader: string
    stop(): Promise<void>
}

const INTERNAL_HEADER = 'x-posthog-internal'
const INTERNAL_SECRET = 'e2e-internal-secret-' + Math.random().toString(36).slice(2, 10)

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

    // 2. Shared deps the harness owns — ingress + runner each receive them
    //    via the factory's overrides, so the two services share one queue +
    //    one bus + one log producer. None of them get re-created.
    const posthogDb = new PosthogDbClient({ dbUrl: POSTHOG_DB_URL })
    const encryption = new EncryptedFields(ENCRYPTION_SALT)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })
    const queueManager = new SessionQueueManager({ pool: { dbUrl: QUEUE_DB_URL } })
    await queueManager.connect()

    const bus: SessionBus = new InMemorySessionBus()

    const logProducer = new KafkaLogProducer({
        brokers: KAFKA_BROKERS,
        topic: LOG_ENTRIES_TOPIC,
        name: 'agent-tests-logs',
    })
    await logProducer.connect().catch((err) => {
        throw wrap(err, 'Kafka', KAFKA_BROKERS)
    })

    // 3. Build ingress + runner via the same factories the bins use.
    const secretsMap = { ...opts.secrets }
    // Per-cluster queue name so a co-running prod-shape agent-runner
    // (started by `hogli start`) doesn't dequeue our test jobs. Random
    // suffix keeps parallel suites isolated.
    const queueName = `e2e-${Math.random().toString(36).slice(2, 10)}`

    const ingress: Ingress = await createIngress({
        config: { domainSuffix: '.e2e.test', routingMode: 'domain', resolverTtlMs: 0 },
        queue: queueManager,
        bus,
        posthogDb,
        repository,
        identities,
        queueName,
        verifyPostHogInternal:
            opts.verifyPostHogInternal ??
            (async (req) => {
                return req.headers[INTERNAL_HEADER] === INTERNAL_SECRET
                    ? { kind: 'service', orgId: 'posthog', caller: 'posthog-internal' }
                    : null
            }),
        loadSecret: async (name) => secretsMap[name] ?? null,
    })
    const { port } = await ingress.start(0)

    const runner: Runner = await createRunner({
        posthogDb,
        repository,
        bus,
        logProducer,
        executor: opts.executor,
        queueName,
        loadSecrets: async (applicationId) => {
            // Test secrets always win. Falls through to encrypted_env for
            // any name not in the map, so prod-shaped agents work too.
            if (!applicationId) {
                return { ...secretsMap }
            }
            try {
                const real = await repository.decryptEnv(applicationId)
                return { ...real, ...secretsMap }
            } catch {
                return { ...secretsMap }
            }
        },
    })
    await runner.start()

    const cleanup = new CleanupRegistry({ posthog, queue })

    return {
        ingressUrl: `http://127.0.0.1:${port}`,
        port,
        posthog,
        queue,
        queueManager,
        bus,
        clickhouse,
        cleanup,
        internalSecret: INTERNAL_SECRET,
        internalHeader: INTERNAL_HEADER,
        async stop() {
            // Order: factory handles → shared deps the harness created.
            await ingress.stop()
            await runner.stop()
            await queueManager.disconnect()
            await posthogDb.disconnect()
            await logProducer.disconnect()
            await posthog.end()
            await queue.end()
        },
    }
}

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
