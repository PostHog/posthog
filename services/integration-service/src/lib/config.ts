// Configuration, read from the environment once at boot and validated there.
//
// Anything missing that the service cannot safely run without exits the process rather
// than failing later on a request path — a credential service that silently starts
// with no KMS key or no client registry is worse than one that refuses to start.
// Local dev is the exception and is explicit about it.

import { getEnv } from './env.js'
import { logger } from './logging.js'

export interface Config {
    port: number
    host: string
    isProduction: boolean
    shutdownGraceMs: number
    shutdownPrestopDelayMs: number

    /** Logical environment (dev | prod-us | prod-eu). Bound into cache keys, AAD and the usage artifact. */
    env: string
    awsRegion: string
    /** Set only in tests / local dev to point the AWS SDK at moto. */
    awsEndpoint: string | undefined

    /** Builds the AWS secret id for a provider, in the shape PostHog/secrets manages. */
    secretIdFor: (provider: string) => string
    /** This service's own secret, holding one signing key per calling deployment. */
    signingKeySecretId: string

    redisUrl: string | undefined
    kmsKeyId: string | undefined
    dekRotationMs: number

    cacheTtlSeconds: number

    usageBucket: string | undefined
    usageKmsKeyId: string | undefined
    usagePublishIntervalMs: number
    retireQuietHours: number

    metricsToken: string
}

function intFromEnv(key: Parameters<typeof getEnv>[0], fallback: number): number {
    const raw = getEnv(key)
    if (!raw) {
        return fallback
    }
    const parsed = Number.parseInt(raw, 10)
    return Number.isNaN(parsed) ? fallback : parsed
}

export function loadConfig(): Config {
    const isProduction = getEnv('NODE_ENV') === 'production'
    // PostHog/secrets names every managed secret `<app>-secrets` and only shows secrets
    // tagged managed-by=secrets-script, so provider credentials have to live under names
    // its CLI and UI resolve. `integrations-stripe` -> `integrations-stripe-secrets`.
    const secretPrefix = getEnv('INTEGRATION_SERVICE_SECRET_PREFIX') ?? 'integrations-'
    const secretSuffix = '-secrets'

    const config: Config = {
        port: intFromEnv('PORT', 8004),
        host: getEnv('HOST') ?? '0.0.0.0',
        isProduction,
        shutdownGraceMs: intFromEnv('SHUTDOWN_GRACE_MS', 15000),
        shutdownPrestopDelayMs: intFromEnv('SHUTDOWN_PRESTOP_DELAY_MS', 5000),

        env: getEnv('INTEGRATION_SERVICE_ENV') ?? 'dev',
        awsRegion: getEnv('AWS_REGION') ?? 'us-east-1',
        awsEndpoint: getEnv('AWS_ENDPOINT_URL'),

        secretIdFor: (provider: string) => `${secretPrefix}${provider}${secretSuffix}`,
        signingKeySecretId: getEnv('INTEGRATION_SERVICE_KEYS_SECRET_ID') ?? `integration-service${secretSuffix}`,

        redisUrl: getEnv('INTEGRATION_SERVICE_REDIS_URL'),
        kmsKeyId: getEnv('INTEGRATION_SERVICE_KMS_KEY_ID'),
        dekRotationMs: intFromEnv('INTEGRATION_SERVICE_DEK_ROTATION_SECONDS', 3600) * 1000,

        cacheTtlSeconds: intFromEnv('INTEGRATION_SERVICE_CACHE_TTL_SECONDS', 300),

        usageBucket: getEnv('INTEGRATION_SERVICE_USAGE_BUCKET'),
        usageKmsKeyId: getEnv('INTEGRATION_SERVICE_USAGE_KMS_KEY_ID'),
        usagePublishIntervalMs: intFromEnv('INTEGRATION_SERVICE_USAGE_PUBLISH_INTERVAL_MS', 300000),
        retireQuietHours: intFromEnv('INTEGRATION_SERVICE_RETIRE_QUIET_HOURS', 24),

        metricsToken: getEnv('INTEGRATION_SERVICE_METRICS_TOKEN') ?? '',
    }

    if (isProduction) {
        const missing: string[] = []
        if (!getEnv('INTEGRATION_SERVICE_ENV')) {
            missing.push('INTEGRATION_SERVICE_ENV')
        }
        // Redis and KMS come as a pair: the L2 cache exists precisely so values are
        // sealed, so running with one and not the other is never what was intended.
        if (!config.redisUrl) {
            missing.push('INTEGRATION_SERVICE_REDIS_URL')
        }
        if (!config.kmsKeyId) {
            missing.push('INTEGRATION_SERVICE_KMS_KEY_ID')
        }
        if (missing.length > 0) {
            logger.error('config:missing_required', { missing })
            process.exit(1)
        }
    }

    if (config.redisUrl && !config.kmsKeyId) {
        logger.error('config:redis_without_kms', {})
        process.exit(1)
    }

    if (!config.usageBucket) {
        logger.warn('config:usage_publishing_disabled', {
            reason: 'INTEGRATION_SERVICE_USAGE_BUCKET is unset',
        })
    }

    return config
}
