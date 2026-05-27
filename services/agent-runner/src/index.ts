/**
 * agent-runner bin entrypoint. Thin wrapper around `createRunner` from
 * `./lib`: load env, hand defaults to the factory, swap in the real
 * Claude-Agent-SDK executor (`AssServerExecutor`), wire SIGTERM / SIGINT,
 * call `start()`. Everything heavier lives in the factory.
 *
 * `AGENT_RUNNER_TEST_EXECUTOR` env-var override selects a deterministic
 * substitute executor for the agent-tests harness's subprocess runner.
 * Unset = production behaviour (real `AssServerExecutor`).
 */
import { reapOrphanedSandboxes } from '@repo/ass-sandbox'
import type { Principal } from '@repo/ass-server/types'

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
import { type SessionExecutor } from './executor'
import { EchoExecutor } from './executor-stub'
import { createRunner } from './lib'
import { type SessionMessage } from './state'
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

    // Pick the executor. Default = the real SDK executor (production path).
    // Tests opt in to a deterministic substitute via `AGENT_RUNNER_TEST_EXECUTOR`
    // — keeps the bin a single entry point for both prod and the agent-tests
    // harness's subprocess runner.
    const testExecutorKind = process.env.AGENT_RUNNER_TEST_EXECUTOR
    if (!testExecutorKind && !config.anthropicApiKey) {
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

    // Factory map: each test-executor kind builds one `SessionExecutor`.
    // Shared by the single-kind selector below AND the `router` kind, which
    // dispatches per-job by reading `__TEST_EXECUTOR` from the app's
    // decrypted env. The router model lets one shared runner serve every
    // e2e suite without each suite spawning its own subprocess.
    const sdkExecutor: SessionExecutor = new AssServerExecutor({
        bundleStore,
        repository,
        sandboxInstances,
        bus,
        logProducer,
    })
    const testExecutors: Record<string, SessionExecutor> = {
        echo: new EchoExecutor(),
        // Render the caller principal into the assistant message so the
        // harness can assert end-to-end (ingress → runner → bus → Kafka → CH).
        'principal-echo': {
            runTurn: (input) =>
                Promise.resolve({
                    kind: 'completed',
                    message: {
                        role: 'assistant',
                        content: renderPrincipal(input.job.principal),
                        at: new Date().toISOString(),
                    },
                    output: {
                        renderedPrincipal: renderPrincipal(input.job.principal),
                        principal: input.job.principal,
                    },
                }),
        },
        // Subscribes to the bus and sleeps up to 2s, observing `cancel`.
        // Powers the /cancel and /listen runtime e2e tests. 2s is the
        // ceiling — long enough for /listen to attach SSE (~100ms in
        // practice) and for /cancel to send through the bus, short
        // enough that an unobserved completion doesn't dominate the
        // suite's wall time. Override via `__TEST_SLEEP_MS` in the
        // app's encrypted env when a test legitimately needs longer.
        'slow-cancellable': {
            runTurn: async (input) => {
                const sessionId = input.job.sessionId
                const sleepCap = Number(input.job.secrets.__TEST_SLEEP_MS ?? 2_000)
                let cancelled = false
                const unsubscribe = await bus.subscribeInput(sessionId, (msg) => {
                    if (msg.type === 'cancel') {
                        cancelled = true
                    }
                })
                try {
                    const start = Date.now()
                    while (!cancelled && Date.now() - start < sleepCap) {
                        await new Promise((r) => setTimeout(r, 50))
                    }
                } finally {
                    await unsubscribe().catch(() => {})
                }
                if (cancelled) {
                    return { kind: 'cancelled' }
                }
                return {
                    kind: 'completed',
                    message: {
                        role: 'assistant',
                        content: 'slow-cancellable: completed without cancel',
                        at: new Date().toISOString(),
                    },
                    output: { ok: true },
                }
            },
        },
        // Forces the worker's failure branch.
        failure: {
            runTurn: () =>
                Promise.resolve({
                    kind: 'failed',
                    error: 'forced failure for e2e test',
                }),
        },
        // Chat-shaped stub: echoes the latest user message back as the
        // assistant reply and returns `awaiting_input` so the worker
        // parks the job. /send wakes the parked job; the next turn
        // echoes the next message. Returns `completed` after the
        // configured number of turns to bound the test.
        //
        // The persistent-chat suites use this to exercise the turn
        // boundary + state persistence without paying Anthropic.
        'chat-echo': {
            runTurn: (input) => {
                const lastUser = lastUserMessage(input.state.messages)
                if (lastUser === null) {
                    return Promise.resolve({
                        kind: 'completed' as const,
                        message: {
                            role: 'assistant' as const,
                            content: 'chat-echo: no user input',
                            at: new Date().toISOString(),
                        },
                        output: { reason: 'no_input' },
                    })
                }
                // Limit: 5 turns by default. Sessions that need more
                // override via `__TEST_CHAT_MAX_TURNS` in the app env.
                const maxTurns = Number(input.job.secrets.__TEST_CHAT_MAX_TURNS ?? 5)
                const nextTurn = input.state.turnCount + 1
                const message = {
                    role: 'assistant' as const,
                    content: `echo: ${lastUser} (turn ${nextTurn})`,
                    at: new Date().toISOString(),
                }
                if (nextTurn >= maxTurns) {
                    return Promise.resolve({
                        kind: 'completed' as const,
                        message,
                        output: { turns: nextTurn },
                    })
                }
                return Promise.resolve({ kind: 'awaiting_input' as const, message, reason: null })
            },
        },
        // Same shape as chat-echo, but sleeps ~3s before responding.
        // Powers the "queued follow-ups arrive while a turn is in
        // flight" cases — a /send during the sleep must land durably.
        'chat-slow': {
            runTurn: async (input) => {
                const lastUser = lastUserMessage(input.state.messages)
                await new Promise((r) => setTimeout(r, Number(input.job.secrets.__TEST_CHAT_SLEEP_MS ?? 3_000)))
                if (lastUser === null) {
                    return {
                        kind: 'completed' as const,
                        message: {
                            role: 'assistant' as const,
                            content: 'chat-slow: no user input',
                            at: new Date().toISOString(),
                        },
                        output: { reason: 'no_input' },
                    }
                }
                return {
                    kind: 'awaiting_input' as const,
                    message: {
                        role: 'assistant' as const,
                        content: `slow-echo: ${lastUser}`,
                        at: new Date().toISOString(),
                    },
                    reason: null,
                }
            },
        },
        // Single-shot variant — completes immediately, never parks.
        // Used by `/send to a completed session → 410` tests.
        'chat-once': {
            runTurn: (input) => {
                const lastUser = lastUserMessage(input.state.messages) ?? '(no input)'
                return Promise.resolve({
                    kind: 'completed' as const,
                    message: {
                        role: 'assistant' as const,
                        content: `once: ${lastUser}`,
                        at: new Date().toISOString(),
                    },
                    output: { turns: 1 },
                })
            },
        },
        sdk: sdkExecutor,
    }

    /**
     * Reads `__TEST_EXECUTOR` from the job's decrypted env. The harness
     * stamps this into `encrypted_env` per app, so a SINGLE runner serves
     * every shape of e2e test without per-suite subprocesses.
     *
     * Falls back to the real SDK when no marker is present. That choice is
     * deliberate: production has no marker and we never want a router
     * default that silently swallows real traffic.
     */
    const routerExecutor: SessionExecutor = {
        runTurn: (input) => {
            const kind = input.job.secrets.__TEST_EXECUTOR
            if (!kind || kind === 'sdk') {
                return sdkExecutor.runTurn(input)
            }
            const inner = testExecutors[kind]
            if (!inner) {
                return Promise.resolve({
                    kind: 'failed',
                    error: `router: unknown __TEST_EXECUTOR='${kind}' — expected one of ${Object.keys(testExecutors).join(', ')}`,
                })
            }
            return inner.runTurn(input)
        },
    }

    let executor: SessionExecutor
    if (!testExecutorKind || testExecutorKind === 'sdk') {
        executor = sdkExecutor
    } else if (testExecutorKind === 'router') {
        logger.warn('AGENT_RUNNER_TEST_EXECUTOR=router — dispatching per-job via __TEST_EXECUTOR in app env')
        executor = routerExecutor
    } else if (testExecutors[testExecutorKind]) {
        logger.warn(`AGENT_RUNNER_TEST_EXECUTOR=${testExecutorKind} — single-kind test executor (legacy mode)`)
        executor = testExecutors[testExecutorKind]
    } else {
        throw new Error(
            `Unknown AGENT_RUNNER_TEST_EXECUTOR='${testExecutorKind}'. Expected: ${['router', 'sdk', ...Object.keys(testExecutors)].join(', ')}.`
        )
    }

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

/**
 * Render the caller principal into a deterministic flat string. Mirrored
 * exactly by services/agent-tests/src/harness/executors.ts so test
 * assertions can compare across both paths (in-process and subprocess).
 */
function renderPrincipal(principal: Principal | null): string {
    if (principal === null) {
        return 'principal: none'
    }
    if (principal.kind === 'service') {
        return `principal: service caller=${principal.caller} org=${principal.orgId}`
    }
    return `principal: user space=${principal.spaceId} userId=${principal.userId} provider=${principal.provider}`
}

/**
 * Walk `state.messages` from the tail back; return the most recent
 * `user`-role message's content, or null if none. Used by the chat-*
 * stub executors to find "what the user just said." Trusts that the
 * worker pushed user messages onto state.messages before calling us.
 */
function lastUserMessage(messages: SessionMessage[]): string | null {
    for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === 'user') {
            return messages[i].content
        }
    }
    return null
}

main().catch((err: unknown) => {
    // Pass the Error instance under `err` (or `error`) so pino's serializer
    // expands message + stack + nested causes — `String(err)` loses all of it.
    logger.error({ err }, 'agent-runner fatal')
    process.exit(1)
})
