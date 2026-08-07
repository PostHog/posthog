// Entry point for the integration-service.
//
// Startup sequence:
//   1. Load and validate configuration.
//   2. Build the AWS clients (Secrets Manager, KMS, S3).
//   3. Load the client registry — a hard failure, since the service cannot authenticate
//      anybody without it.
//   4. Connect Redis (optional; without it the service runs on L1 alone).
//   5. Warm every provider, then flip readiness.
//   6. Start the HTTP server and the background refresh + usage publish timers.

import { KMSClient } from '@aws-sdk/client-kms'
import { S3Client } from '@aws-sdk/client-s3'
import { SecretsManagerClient } from '@aws-sdk/client-secrets-manager'
import { serve } from '@hono/node-server'
import Redis from 'ioredis'

import { JwtVerifier } from './auth/jwt.js'
import { SigningKeyLoader } from './auth/registry.js'
import { credentialProvider } from './aws/credentials.js'
import { EnvelopeCipher } from './cache/envelope.js'
import { SecretCache } from './cache/secretCache.js'
import { createApp, type Lifecycle } from './http/app.js'
import { loadConfig } from './lib/config.js'
import { logger } from './lib/logging.js'
import { observeKms } from './metrics.js'
import { createSecretsManagerStore } from './store/secretsManager.js'
import { UsagePublisher } from './usage/publisher.js'
import { UsageRecorder } from './usage/recorder.js'

/** Spread a periodic task over its interval so replicas do not sync up on the store. */
function jittered(intervalMs: number): number {
    return intervalMs / 2 + Math.random() * intervalMs
}

function scheduleJittered(intervalMs: number, task: () => Promise<void>): NodeJS.Timeout {
    const timer = setTimeout(function run() {
        void task().finally(() => timer.refresh?.())
    }, jittered(intervalMs))
    // Unref so a pending timer never holds the process open during shutdown.
    timer.unref()
    return timer
}

async function main(): Promise<void> {
    const config = loadConfig()
    // `credentials` is passed explicitly so the SDK never consults its default chain —
    // see src/aws/credentials.ts for why that matters on this service in particular.
    const awsCommon = {
        region: config.awsRegion,
        credentials: credentialProvider(),
        ...(config.awsEndpoint ? { endpoint: config.awsEndpoint, forcePathStyle: true } : {}),
    }

    const secretsManager = new SecretsManagerClient(awsCommon)
    const kms = new KMSClient(awsCommon)
    const s3 = new S3Client(awsCommon)

    const signingKeys = new SigningKeyLoader(secretsManager, config.secretId)
    try {
        await signingKeys.load()
    } catch (err) {
        logger.error('startup:signing_keys_load_failed', {
            secretId: config.secretId,
            error: err instanceof Error ? err.message : String(err),
        })
        process.exit(1)
    }

    let redis: Redis | undefined
    if (config.redisUrl) {
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        redis = new Redis(config.redisUrl, {
            lazyConnect: true,
            maxRetriesPerRequest: 3,
            enableOfflineQueue: false,
            connectTimeout: 5000,
            commandTimeout: 2000,
            keepAlive: 30000,
            retryStrategy: (times: number) => Math.min(times * 200, 2000),
        })
        redis.on('error', (err: Error) => logger.error('redis:error', { error: err.message }))
        try {
            await redis.connect()
            logger.info('redis:connected', {})
        } catch (err) {
            // Redis is a cache tier, not the source of truth. Losing it costs latency
            // and extra Secrets Manager reads; it must not stop the service booting.
            logger.error('redis:connect_failed', { error: err instanceof Error ? err.message : String(err) })
            redis = undefined
        }
    } else {
        logger.warn('redis:disabled', { reason: 'INTEGRATION_SERVICE_REDIS_URL is unset — L1 cache only' })
    }

    const cipher = new EnvelopeCipher({
        kms,
        // Guarded in loadConfig: a configured Redis without a KMS key exits at boot.
        keyId: config.kmsKeyId ?? '',
        env: config.env,
        rotationMs: config.dekRotationMs,
        onKms: observeKms,
    })

    const cache = new SecretCache({
        store: createSecretsManagerStore({ client: secretsManager, secretId: config.secretId }),
        cipher,
        redis,
        env: config.env,
        ttlSeconds: config.cacheTtlSeconds,
    })

    const recorder = new UsageRecorder({ redis, env: config.env })
    const lifecycle: Lifecycle = { shuttingDown: false, ready: false }

    const app = createApp({
        verifier: new JwtVerifier(signingKeys),
        lifecycle,
        resolveDeps: {
            loadSecrets: () => cache.get(),
            recorder,
        },
        metricsToken: config.metricsToken,
    })

    await cache.warm()
    lifecycle.ready = true

    const server = serve({ fetch: app.fetch, port: config.port, hostname: config.host }, (info) => {
        logger.info('server:started', { host: config.host, port: info.port, env: config.env })
    })

    // Background refresh keeps the cache warm ahead of expiry, so a rotation reaches
    // callers within a TTL without anyone paying a cold read.
    scheduleJittered(config.cacheTtlSeconds * 1000, async () => {
        await cache.warm()
    })
    scheduleJittered(config.cacheTtlSeconds * 1000, async () => {
        await signingKeys.reload()
    })

    if (config.usageBucket) {
        const publisher = new UsagePublisher({
            s3,
            bucket: config.usageBucket,
            kmsKeyId: config.usageKmsKeyId,
            env: config.env,
            quietWindowHours: config.retireQuietHours,
            recorder,
            loadSnapshot: () => cache.get(),
        })
        scheduleJittered(config.usagePublishIntervalMs, () => publisher.publish())
    }

    registerShutdown({ server, lifecycle, redis, config })
}

function registerShutdown(opts: {
    server: { close: (cb: () => void) => void }
    lifecycle: Lifecycle
    redis: Redis | undefined
    config: { shutdownGraceMs: number; shutdownPrestopDelayMs: number }
}): void {
    let started = false
    const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

    const shutdown = async (signal: string): Promise<void> => {
        if (started) {
            return
        }
        started = true
        logger.info('shutdown:start', { signal })
        opts.lifecycle.shuttingDown = true

        const startedAt = Date.now()
        if (opts.config.shutdownPrestopDelayMs > 0) {
            await sleep(opts.config.shutdownPrestopDelayMs)
        }
        const drainBudget = Math.max(opts.config.shutdownGraceMs - (Date.now() - startedAt), 1000)
        await Promise.race([new Promise<void>((resolve) => opts.server.close(() => resolve())), sleep(drainBudget)])

        if (opts.redis) {
            try {
                await opts.redis.quit()
            } catch (err) {
                logger.error('shutdown:redis_quit_failed', {
                    error: err instanceof Error ? err.message : String(err),
                })
            }
        }
        logger.info('shutdown:complete', {})
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
