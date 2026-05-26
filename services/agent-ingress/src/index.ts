/**
 * agent-ingress bin entrypoint. Thin wrapper around `createIngress` from
 * `./lib`: load env defaults, hand them to the factory, register SIGTERM /
 * SIGINT handlers, and call `start()`. Anything more interesting (custom
 * deps, behaviour overrides, swapping in shared infra for tests) belongs
 * in the factory — keeping this file tiny is the point.
 */
import { loadDevEnv, logger } from '@posthog/agent-core'

import { createIngress } from './lib'

loadDevEnv()

async function main(): Promise<void> {
    const ingress = await createIngress()
    const { port } = await ingress.start()
    logger.info('agent-ingress listening', {
        port,
        routingMode: ingress.deps.routingMode,
        domainSuffix: ingress.deps.routingMode === 'domain' ? ingress.deps.domainSuffix : undefined,
    })

    const shutdown = async (signal: string): Promise<void> => {
        logger.info('agent-ingress shutting down', { signal })
        await ingress.stop()
        process.exit(0)
    }
    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    logger.error({ err }, 'agent-ingress fatal')
    process.exit(1)
})
