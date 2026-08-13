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

    /** Serves /metrics on its own listener, kept off the ingress like every other service. */
    metricsPort: number
}

function intFromEnv(key: string, fallback: number, min = 0): number {
    const raw = process.env[key]
    if (!raw) {
        return fallback
    }
    // Fail loudly rather than default or truncate: "30abc" must not run as 30, and a
    // zero reload interval would re-read the mount in a 1ms setInterval loop.
    if (!/^\d+$/.test(raw) || Number.parseInt(raw, 10) < min) {
        throw new Error(`${key} must be an integer >= ${min}, got ${JSON.stringify(raw)}`)
    }
    return Number.parseInt(raw, 10)
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
        reloadSeconds: intFromEnv('INTEGRATION_SERVICE_RELOAD_SECONDS', 30, 1),

        metricsPort: intFromEnv('INTEGRATION_SERVICE_METRICS_PORT', 9090),
    }

    if (process.env.NODE_ENV === 'production' && !process.env.INTEGRATION_SERVICE_ENV) {
        throw new Error('missing required configuration: INTEGRATION_SERVICE_ENV')
    }

    return config
}
