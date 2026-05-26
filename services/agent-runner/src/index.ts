/**
 * agent-runner bin entrypoint. Thin wrapper around `createRunner` from
 * `./lib`: load env, hand defaults to the factory, swap in the real
 * Claude-Agent-SDK executor (`AssServerExecutor`), wire SIGTERM / SIGINT,
 * call `start()`. Everything heavier lives in the factory.
 */
import { reapOrphanedSandboxes } from '@repo/ass-sandbox'

import {
    ApplicationsRepository,
    BundleStore,
    EncryptedFields,
    InMemorySessionBus,
    KafkaLogProducer,
    PosthogDbClient,
    RedisSessionBus,
    SandboxInstancesRepository,
    type SessionBus,
    bundleStoreConfigFromEnv,
    loadDevEnv,
    logger,
} from '@posthog/agent-core'

import { AssServerExecutor } from './ass-server-executor'
import { loadConfig } from './config'
import { createRunner } from './lib'
import { selectToolSandboxKind } from './tool-sandbox'

loadDevEnv()

async function main(): Promise<void> {
    logger.info('agent-runner booting', { node: process.version, pid: process.pid })
    const config = loadConfig()
    logger.info('agent-runner config loaded', {
        queueName: config.queueName,
        kafkaTopic: config.kafkaLogEntriesTopic,
        hasRedis: Boolean(config.redisUrl),
    })

    // Sweep tool-sandbox containers orphaned by a previous crashed run.
    try {
        if (selectToolSandboxKind() === 'docker') {
            const reaped = await reapOrphanedSandboxes({ log: (line) => logger.info(line) })
            if (reaped > 0) {
                logger.info('reaped orphaned tool-sandbox containers', { count: reaped })
            }
        }
    } catch (err) {
        logger.warn({ err }, 'orphaned-sandbox reap skipped')
    }

    // The SDK executor pulls in @anthropic-ai/claude-agent-sdk (ESM,
    // awkward to load via ts-jest), so the factory doesn't pre-wire it —
    // the bin constructs the shared deps, the executor, and hands the
    // bundle to the factory.
    //
    // ANTHROPIC_API_KEY is optional in the config schema so the runner can
    // boot under a test executor (EchoExecutor / PrincipalEchoExecutor)
    // without a credential. The bin enforces it here, before constructing
    // AssServerExecutor — fail fast in prod, stay loose for tests.
    if (!config.anthropicApiKey) {
        throw new Error(
            'ANTHROPIC_API_KEY is required to run the SDK executor — set it in your shell or repo-root .env'
        )
    }
    const posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })

    const bus: SessionBus = config.redisUrl ? new RedisSessionBus({ url: config.redisUrl }) : new InMemorySessionBus()
    if (!config.redisUrl) {
        logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    }

    logger.info('connecting log producer', { brokers: config.kafkaBrokers, topic: config.kafkaLogEntriesTopic })
    const logProducer = new KafkaLogProducer({
        brokers: config.kafkaBrokers,
        topic: config.kafkaLogEntriesTopic,
        name: 'agent-runner-logs',
    })
    await logProducer.connect()
    logger.info('log producer connected')

    const bundleStore = new BundleStore(bundleStoreConfigFromEnv())

    const executor = new AssServerExecutor({ bundleStore, repository, sandboxInstances, bus, logProducer })

    const runner = await createRunner({
        posthogDb,
        repository,
        bus,
        logProducer,
        executor,
    })

    await runner.start()
    logger.info('agent-runner started', { queueName: config.queueName, kafkaTopic: config.kafkaLogEntriesTopic })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-runner shutting down', { signal })
        await runner.stop()
        // Bin-owned resources the factory left alone.
        await bus.disconnect()
        await logProducer.disconnect()
        await posthogDb.disconnect()
        bundleStore.destroy()
        process.exit(0)
    }
    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    // Pass the Error instance under `err` (or `error`) so pino's serializer
    // expands message + stack + nested causes — `String(err)` loses all of it.
    logger.error({ err }, 'agent-runner fatal')
    process.exit(1)
})
