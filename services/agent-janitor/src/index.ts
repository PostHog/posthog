import { terminateDockerSandbox } from '@repo/ass-sandbox'

import {
    PosthogDbClient,
    SandboxInstanceJanitor,
    SandboxInstancesRepository,
    SessionQuery,
    SessionQueueJanitor,
    loadDevEnv,
    logger,
} from '@posthog/agent-core'

import { loadConfig } from './config'
import { buildServer } from './server'

loadDevEnv()

async function main(): Promise<void> {
    const config = loadConfig()

    if (!config.internalApiSharedKey) {
        logger.warn(
            'agent-janitor starting without AGENT_INTERNAL_API_SHARED_KEY — /internal routes will refuse traffic'
        )
    }

    const query = new SessionQuery({ pool: { dbUrl: config.queueDbUrl } })
    await query.connect()

    const janitor = new SessionQueueJanitor({
        pool: { dbUrl: config.queueDbUrl },
        cleanupIntervalMs: config.janitorIntervalMs,
        stallTimeoutMs: config.janitorStallTimeoutMs,
        maxTouchCount: config.janitorMaxTouchCount,
        cleanupGraceMs: config.janitorCleanupGraceMs,
    })
    await janitor.start()

    // Periodically reap orphan tool-sandbox rows. Skipped when no PostHog DB
    // URL is configured (test envs) or sweep interval is 0.
    let sandboxJanitor: SandboxInstanceJanitor | null = null
    let posthogDb: PosthogDbClient | null = null
    if (config.posthogDbUrl && config.sandboxJanitorIntervalMs > 0) {
        posthogDb = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
        const sandboxInstances = new SandboxInstancesRepository({ db: posthogDb })
        sandboxJanitor = new SandboxInstanceJanitor({
            repo: sandboxInstances,
            intervalMs: config.sandboxJanitorIntervalMs,
            staleMs: config.sandboxJanitorStaleMs,
            terminate: async (row) => {
                if (row.providerKind === 'docker') {
                    // Best-effort: only succeeds when the janitor is colocated
                    // with the runner host. The DB row gets marked terminated
                    // either way — Docker labels + in-runner reaper cover the
                    // cross-host gap.
                    await terminateDockerSandbox(row.providerSandboxId)
                    return
                }
                // Modal arm lands when ModalToolSandbox is wired in. Until
                // then, a Modal row falling through here means a Modal
                // sandbox is leaking — surface it loudly.
                throw new Error(`no terminator for provider=${row.providerKind} id=${row.providerSandboxId}`)
            },
        })
        await sandboxJanitor.start()
        logger.info('sandbox janitor started', {
            intervalMs: config.sandboxJanitorIntervalMs,
            staleMs: config.sandboxJanitorStaleMs,
        })
    } else {
        logger.info('sandbox janitor disabled', {
            posthogDbUrlConfigured: Boolean(config.posthogDbUrl),
            sandboxJanitorIntervalMs: config.sandboxJanitorIntervalMs,
        })
    }

    const app = buildServer({ query, internalApiSharedKey: config.internalApiSharedKey })

    const server = app.listen(config.port, () => {
        logger.info('agent-janitor listening', { port: config.port })
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-janitor shutting down', { signal })
        server.close()
        await janitor.stop()
        if (sandboxJanitor) {
            await sandboxJanitor.stop()
        }
        if (posthogDb) {
            await posthogDb.disconnect()
        }
        await query.disconnect()
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err) => {
    logger.error('agent-janitor fatal', { error: String(err) })
    process.exit(1)
})
