/**
 * `createRunner` — the public factory for wiring up an `agent-runner`
 * instance. Used by both the runnable bin (`./index.ts`) and the e2e test
 * harness (`services/agent-tests`) so the two paths stay in lockstep.
 *
 * The factory constructs anything you don't override from env defaults
 * (`loadConfig()`), wires up the `RunnerWorker`, and returns a handle with
 * `start()` / `stop()`. It does NOT poll the queue until you call `start()`.
 *
 * Ownership-aware shutdown: `stop()` disposes the deps the factory created
 * itself. Shared deps you pass in (queue pool config / bus / posthogDb /
 * logProducer) stay your responsibility.
 *
 * Deliberately omits `AssServerExecutor` from the default — it pulls in the
 * Claude Agent SDK (ESM, awkward to load via ts-jest). Callers that want
 * the SDK executor instantiate `AssServerExecutor` explicitly and pass it
 * via `overrides.executor`; the test harness substitutes `EchoExecutor` /
 * `PrincipalEchoExecutor` instead.
 */
import {
    ApplicationsRepository,
    EncryptedFields,
    InMemorySessionBus,
    KafkaLogProducer,
    type LogProducer,
    PosthogDbClient,
    RedisSessionBus,
    SessionBus,
    logger,
} from '@posthog/agent-core'

import { type RunnerConfig, loadConfig } from './config'
import { type SessionExecutor } from './executor'
import { EchoExecutor } from './executor-stub'
import { RunnerWorker } from './worker'

export { RunnerWorker, type RunnerWorkerConfig } from './worker'
export {
    type ExecutorJobContext,
    type ExecutorTurnInput,
    type ExecutorTurnOutput,
    type SessionExecutor,
} from './executor'
export { EchoExecutor } from './executor-stub'

export interface RunnerOverrides {
    /** Defaults: env-derived via `loadConfig()`. Anything missing falls back to dev defaults. */
    config?: Partial<RunnerConfig>

    /* === Shared deps (provide to share across ingress + runner in tests) === */
    posthogDb?: PosthogDbClient
    repository?: ApplicationsRepository
    bus?: SessionBus
    logProducer?: LogProducer

    /* === Behaviour overrides === */
    /**
     * Replace the SessionExecutor. Defaults to `EchoExecutor` (a no-op
     * completion) so the runner can boot without the Claude Agent SDK —
     * see the file-level comment. The real bin overrides this with
     * `AssServerExecutor`; tests use `PrincipalEchoExecutor`.
     */
    executor?: SessionExecutor
    /**
     * Override the secret resolver. Default reads from the application's
     * encrypted_env via `ApplicationsRepository.decryptEnv`.
     */
    loadSecrets?: (applicationId: string | null) => Promise<Record<string, string>>

    /**
     * Queue name to consume from. Defaults to the value from `loadConfig()`
     * (env-derived, `'default'` if unset). Tests override this for queue
     * isolation from a co-running prod-shape runner.
     */
    queueName?: string
}

export interface Runner {
    /** The underlying queue worker. Exposed for inspection / direct lifecycle calls. */
    readonly worker: RunnerWorker
    /** Begin polling the queue. */
    start(): Promise<void>
    /** Drain in-flight, stop polling, dispose owned deps. Idempotent. */
    stop(): Promise<void>
}

export async function createRunner(overrides: RunnerOverrides = {}): Promise<Runner> {
    const config = { ...loadConfig(), ...overrides.config }

    const owned: Array<() => Promise<void>> = []

    const posthogDb =
        overrides.posthogDb ??
        (() => {
            const db = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
            owned.push(() => db.disconnect())
            return db
        })()

    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = overrides.repository ?? new ApplicationsRepository({ db: posthogDb, encryption })

    const bus = overrides.bus ?? createDefaultBus(config)
    if (!overrides.bus) {
        owned.push(() => bus.disconnect())
    }

    const logProducer =
        overrides.logProducer ??
        (await (async () => {
            const producer = new KafkaLogProducer({
                brokers: config.kafkaBrokers,
                topic: config.kafkaLogEntriesTopic,
                name: 'agent-runner-logs',
            })
            await producer.connect()
            owned.push(() => producer.disconnect())
            return producer
        })())

    const worker = new RunnerWorker({
        pool: { dbUrl: config.queueDbUrl },
        queueName: overrides.queueName ?? config.queueName,
        concurrency: config.concurrency,
        executor: overrides.executor ?? new EchoExecutor(),
        bus,
        logProducer,
        loadSecrets:
            overrides.loadSecrets ??
            (async (applicationId: string | null): Promise<Record<string, string>> => {
                if (!applicationId) {
                    return {}
                }
                return repository.decryptEnv(applicationId)
            }),
    })

    let started = false
    return {
        worker,
        async start(): Promise<void> {
            if (started) {
                throw new Error('createRunner: start() called twice')
            }
            started = true
            await worker.start()
        },
        async stop(): Promise<void> {
            if (started) {
                try {
                    await worker.stop()
                } catch (err) {
                    logger.warn({ err }, 'createRunner: worker.stop() threw')
                }
            }
            for (const dispose of owned.reverse()) {
                try {
                    await dispose()
                } catch (err) {
                    logger.warn({ err }, 'createRunner: dispose threw')
                }
            }
            owned.length = 0
        },
    }
}

function createDefaultBus(config: RunnerConfig): SessionBus {
    if (config.redisUrl) {
        return new RedisSessionBus({ url: config.redisUrl })
    }
    logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    return new InMemorySessionBus()
}
