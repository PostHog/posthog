// Configuration, read from the environment once at boot. Anything missing or malformed
// that the service cannot safely run without fails the boot rather than a request later.

export interface Config {
    port: number
    host: string
    /** Wait before draining, so Kubernetes has removed the pod from its endpoints first. */
    shutdownPrestopDelayMs: number

    /** Logical environment (dev | prod-us | prod-eu). */
    env: string

    /** Directory the Kubernetes Secret is mounted at. */
    mountDir: string

    /** How often to re-read the mount. Kubelet updates it in roughly 60-90s. */
    reloadSeconds: number

    metricsToken: string
}

function intFromEnv(key: string, fallback: number): number {
    const raw = process.env[key]
    if (!raw) {
        return fallback
    }
    const parsed = Number.parseInt(raw, 10)
    // Fail loudly rather than default: a malformed reload interval silently falling back
    // would run a cadence the operator did not set.
    if (Number.isNaN(parsed)) {
        throw new Error(`${key} is not a number: ${JSON.stringify(raw)}`)
    }
    return parsed
}

export function loadConfig(): Config {
    const config: Config = {
        port: intFromEnv('PORT', 8004),
        host: process.env.HOST ?? '0.0.0.0',
        shutdownPrestopDelayMs: intFromEnv('SHUTDOWN_PRESTOP_DELAY_MS', 5000),

        env: process.env.INTEGRATION_SERVICE_ENV ?? 'dev',

        mountDir: process.env.INTEGRATION_SERVICE_SECRETS_DIR ?? '/etc/integration-secrets',

        // Shorter than kubelet's own sync so a rotation is visible within about a minute
        // of the mount changing.
        reloadSeconds: intFromEnv('INTEGRATION_SERVICE_RELOAD_SECONDS', 30),

        metricsToken: process.env.INTEGRATION_SERVICE_METRICS_TOKEN ?? '',
    }

    if (process.env.NODE_ENV === 'production') {
        const missing: string[] = []
        if (!process.env.INTEGRATION_SERVICE_ENV) {
            missing.push('INTEGRATION_SERVICE_ENV')
        }
        // /metrics carries no credential values, but the resolve counter is a precise map
        // of which deployment reads which credential, so exposing it must be deliberate.
        if (!config.metricsToken) {
            missing.push('INTEGRATION_SERVICE_METRICS_TOKEN')
        }
        if (missing.length > 0) {
            throw new Error(`missing required configuration: ${missing.join(', ')}`)
        }
    }

    return config
}
