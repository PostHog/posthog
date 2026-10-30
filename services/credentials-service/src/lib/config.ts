// Configuration, read from the environment once at boot. Anything missing or malformed
// that the service cannot safely run without fails the boot rather than a request later.

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/** Where the pod's service account credentials are projected. */
export const SERVICE_ACCOUNT_DIR = '/var/run/secrets/kubernetes.io/serviceaccount'

export type SecretSourceKind = 'directory' | 'kubernetes'

const SECRET_SOURCES: readonly SecretSourceKind[] = ['directory', 'kubernetes']

/** How to reach the Kubernetes Secret through the API server. */
export interface KubernetesSourceConfig {
    /** Base URL of the API server, e.g. `https://10.0.0.1:443`. */
    apiUrl: string
    namespace: string
    secretName: string
    /** Re-read on every request: the projected token rotates. */
    tokenFile: string
    caFile: string
}

export interface Config {
    port: number
    host: string
    /** Wait before draining, so Kubernetes has removed the pod from its endpoints first. */
    shutdownPrestopDelayMs: number

    /** Logical environment (dev | prod-us | prod-eu). */
    env: string

    /** Directory the Kubernetes Secret is mounted at. Read when no `kubernetes` source is set. */
    mountDir: string

    /**
     * Set when CREDENTIALS_SERVICE_SECRET_SOURCE is `kubernetes`: the service then reads the
     * Secret through the API server instead of from `mountDir`.
     */
    kubernetes?: KubernetesSourceConfig

    /**
     * How often to re-read the secret. For the directory source this is the only refresh. For
     * the kubernetes source it is a safety re-fetch next to the watch, so a watch that stalls
     * without an error cannot leave the pod stale for longer than this.
     */
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

function secretSourceFromEnv(): SecretSourceKind {
    const raw = process.env.CREDENTIALS_SERVICE_SECRET_SOURCE
    if (!raw) {
        return 'directory'
    }
    const kind = SECRET_SOURCES.find((source) => source === raw)
    if (!kind) {
        throw new Error(
            `CREDENTIALS_SERVICE_SECRET_SOURCE must be one of ${SECRET_SOURCES.join(', ')}, got ${JSON.stringify(raw)}`
        )
    }
    return kind
}

// Both names go into an API path, so a value outside the Kubernetes naming rules must fail
// the boot instead of building a different request.
const DNS_SUBDOMAIN = /^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$/
const DNS_LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/

function kubernetesFromEnv(serviceAccountDir: string): KubernetesSourceConfig {
    const host = process.env.KUBERNETES_SERVICE_HOST
    const port = process.env.KUBERNETES_SERVICE_PORT
    if (!host || !port) {
        throw new Error(
            'CREDENTIALS_SERVICE_SECRET_SOURCE=kubernetes needs KUBERNETES_SERVICE_HOST and KUBERNETES_SERVICE_PORT'
        )
    }
    if (!/^\d+$/.test(port)) {
        throw new Error(`KUBERNETES_SERVICE_PORT must be an integer, got ${JSON.stringify(port)}`)
    }

    const secretName = process.env.CREDENTIALS_SERVICE_SECRET_NAME || 'credentials-service-secrets'
    if (!DNS_SUBDOMAIN.test(secretName)) {
        throw new Error(`CREDENTIALS_SERVICE_SECRET_NAME is not a valid Secret name: ${JSON.stringify(secretName)}`)
    }

    let namespace = process.env.CREDENTIALS_SERVICE_SECRET_NAMESPACE
    if (!namespace) {
        const namespaceFile = join(serviceAccountDir, 'namespace')
        try {
            namespace = readFileSync(namespaceFile, 'utf8').trim()
        } catch {
            throw new Error(`CREDENTIALS_SERVICE_SECRET_NAMESPACE is unset and ${namespaceFile} is unreadable`)
        }
    }
    if (!DNS_LABEL.test(namespace)) {
        throw new Error(`the Secret namespace is not a valid namespace name: ${JSON.stringify(namespace)}`)
    }

    return {
        // An IPv6 service host needs brackets to form a URL.
        apiUrl: `https://${host.includes(':') ? `[${host}]` : host}:${port}`,
        namespace,
        secretName,
        tokenFile: join(serviceAccountDir, 'token'),
        caFile: join(serviceAccountDir, 'ca.crt'),
    }
}

export function loadConfig(serviceAccountDir = SERVICE_ACCOUNT_DIR): Config {
    const config: Config = {
        port: intFromEnv('PORT', 8004),
        host: process.env.HOST ?? '0.0.0.0',
        shutdownPrestopDelayMs: intFromEnv('SHUTDOWN_PRESTOP_DELAY_MS', 5000),

        env: process.env.CREDENTIALS_SERVICE_ENV ?? 'dev',

        mountDir: process.env.CREDENTIALS_SERVICE_SECRETS_DIR ?? '/etc/credentials-secrets',

        // Kubelet syncs a mounted Secret on each node on its own schedule, so for the directory
        // source a change lands on different pods up to a minute or more apart whatever this
        // is. The kubernetes source gets changes from its watch within about a second.
        reloadSeconds: intFromEnv('CREDENTIALS_SERVICE_RELOAD_SECONDS', 30, 1),

        metricsPort: intFromEnv('CREDENTIALS_SERVICE_METRICS_PORT', 9090),
    }

    if (secretSourceFromEnv() === 'kubernetes') {
        config.kubernetes = kubernetesFromEnv(serviceAccountDir)
    }

    if (process.env.NODE_ENV === 'production' && !process.env.CREDENTIALS_SERVICE_ENV) {
        throw new Error('missing required configuration: CREDENTIALS_SERVICE_ENV')
    }

    return config
}
