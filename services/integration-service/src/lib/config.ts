// Configuration, read from the environment once at boot and validated there.
//
// Anything missing that the service cannot safely run without exits the process rather
// than failing later on a request path. A credential service that silently starts with no
// secret mount is worse than one that refuses to start.

import { getEnv } from './env.js'
import { logger } from './logging.js'

export interface Config {
    port: number
    host: string
    isProduction: boolean
    shutdownGraceMs: number
    shutdownPrestopDelayMs: number

    /** Logical environment (dev | prod-us | prod-eu). Recorded on the usage artifact. */
    env: string
    awsRegion: string
    /** Set only in tests / local dev to point the AWS SDK at a mock. */
    awsEndpoint: string | undefined

    /** Directory the Kubernetes Secret is mounted at. */
    secretsDir: string
    /** From the chart\'s `psql:` harness. Unset disables usage recording (local dev). */
    databaseUrl: string | undefined

    /** How often to re-read the mount. Kubelet updates it in roughly 60-90s. */
    reloadSeconds: number
    usageFlushMs: number
    retentionDays: number
    retireQuietHours: number

    usageBucket: string | undefined
    usageKmsKeyId: string | undefined
    usagePublishIntervalMs: number

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

    const config: Config = {
        port: intFromEnv('PORT', 8004),
        host: getEnv('HOST') ?? '0.0.0.0',
        isProduction,
        shutdownGraceMs: intFromEnv('SHUTDOWN_GRACE_MS', 15000),
        shutdownPrestopDelayMs: intFromEnv('SHUTDOWN_PRESTOP_DELAY_MS', 5000),

        env: getEnv('INTEGRATION_SERVICE_ENV') ?? 'dev',
        awsRegion: getEnv('AWS_REGION') ?? 'us-east-1',
        awsEndpoint: getEnv('AWS_ENDPOINT_URL'),

        secretsDir: getEnv('INTEGRATION_SERVICE_SECRETS_DIR') ?? '/etc/integration-secrets',
        databaseUrl: getEnv('INTEGRATION_SERVICE_DATABASE_URL'),

        // Shorter than kubelet\'s own sync so a rotation is visible within about a minute
        // of the mount changing. Reading a handful of small files is cheap.
        reloadSeconds: intFromEnv('INTEGRATION_SERVICE_RELOAD_SECONDS', 30),
        usageFlushMs: intFromEnv('INTEGRATION_SERVICE_USAGE_FLUSH_MS', 10000),
        retentionDays: intFromEnv('INTEGRATION_SERVICE_RETENTION_DAYS', 9),
        retireQuietHours: intFromEnv('INTEGRATION_SERVICE_RETIRE_QUIET_HOURS', 24),

        usageBucket: getEnv('INTEGRATION_SERVICE_USAGE_BUCKET'),
        usageKmsKeyId: getEnv('INTEGRATION_SERVICE_USAGE_KMS_KEY_ID'),
        usagePublishIntervalMs: intFromEnv('INTEGRATION_SERVICE_USAGE_PUBLISH_INTERVAL_MS', 300000),

        metricsToken: getEnv('INTEGRATION_SERVICE_METRICS_TOKEN') ?? '',
    }

    if (isProduction) {
        const missing: string[] = []
        if (!getEnv('INTEGRATION_SERVICE_ENV')) {
            missing.push('INTEGRATION_SERVICE_ENV')
        }
        // Without it the usage rollup silently stops, and the rollup is what decides when
        // an old credential is safe to retire.
        if (!config.databaseUrl) {
            missing.push('INTEGRATION_SERVICE_DATABASE_URL')
        }
        // /metrics carries no credential values, but it does carry
        // integration_secret_resolve_total{deployment,product,provider,key} — a precise
        // map of which deployment reads which credential. Leaving it open by default made
        // that a decision nobody took; requiring the token makes exposing it deliberate.
        if (!config.metricsToken) {
            missing.push('INTEGRATION_SERVICE_METRICS_TOKEN')
        }
        if (missing.length > 0) {
            logger.error('config:missing_required', { missing })
            process.exit(1)
        }
        // Only ever meant for pointing local dev and tests at a mock. Honoured in
        // production it is a fail-open in the one module written to fail closed: it skips
        // IRSA for static throwaway credentials and sends the S3 client, the only AWS
        // client left, at whatever that URL serves. See aws/credentials.ts.
        if (config.awsEndpoint) {
            logger.error('config:aws_endpoint_override_in_production', { endpoint: config.awsEndpoint })
            process.exit(1)
        }
    }

    if (!config.usageBucket) {
        logger.warn('config:usage_publishing_disabled', { reason: 'INTEGRATION_SERVICE_USAGE_BUCKET is unset' })
    }

    return config
}
