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
    // Test-mode overrides. Both gated on env presence; production never
    // sets these. Used by services/agent-tests's subprocess harness to
    // configure the in-process behaviour ingress can't otherwise read
    // from config.
    const testInternalSecret = process.env.AGENT_INGRESS_TEST_INTERNAL_SECRET
    const testSecretsJson = process.env.AGENT_INGRESS_TEST_SECRETS_JSON
    const testSecrets: Record<string, string> = testSecretsJson ? JSON.parse(testSecretsJson) : {}

    const ingress = await createIngress({
        queueName: process.env.AGENT_INGRESS_QUEUE_NAME || undefined,
        verifyPostHogInternal: testInternalSecret
            ? async (req) =>
                  req.headers['x-posthog-internal'] === testInternalSecret
                      ? { kind: 'service', orgId: 'posthog', caller: 'posthog-internal' }
                      : null
            : undefined,
        loadSecret: Object.keys(testSecrets).length > 0 ? async (name) => testSecrets[name] ?? null : undefined,
    })
    const { port } = await ingress.start()
    logger.info('agent-ingress listening', {
        port,
        routingMode: ingress.deps.routingMode,
        domainSuffix: ingress.deps.routingMode === 'domain' ? ingress.deps.domainSuffix : undefined,
        testMode: Boolean(testInternalSecret || testSecretsJson),
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
