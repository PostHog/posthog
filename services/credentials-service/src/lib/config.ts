// Configuration, read from the environment once at boot. Anything missing or malformed
// that the service cannot safely run without fails the boot rather than a request later.

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { isProductionEnv } from '../db/role-guard'

/** Where the pod's service account credentials are projected. */
export const SERVICE_ACCOUNT_DIR = '/var/run/secrets/kubernetes.io/serviceaccount'

export type SecretSourceKind = 'directory' | 'kubernetes'

const SECRET_SOURCES: readonly SecretSourceKind[] = ['directory', 'kubernetes']

export type KmsProviderKind = 'aws' | 'local'

const KMS_PROVIDERS: readonly KmsProviderKind[] = ['aws', 'local']

/** Wraps the per-record data keys with an AWS KMS key. */
export interface AwsKmsConfig {
    provider: 'aws'
    /** Key alias (`alias/...`), key id or key ARN of the single-region key that wraps new data keys. */
    keyId: string
    /** Falls back to the SDK's own region resolution (`AWS_REGION`) when unset. */
    region?: string
    /** A VPC endpoint, or a local KMS emulator. */
    endpoint?: string
    /** Unset means the client connects to KMS directly and ignores HTTP_PROXY/HTTPS_PROXY. */
    proxyUrl?: string
}

/** Wraps the per-record data keys with AES keys from config. For dev, CI and hobby. */
export interface LocalKmsConfig {
    provider: 'local'
    /** 32-byte keys. The first one wraps new data keys. All of them unwrap. */
    keys: Buffer[]
}

export type KmsConfig = AwsKmsConfig | LocalKmsConfig

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

/** The service's own Postgres database. */
export interface DatabaseConfig {
    url: string
    poolSize: number
    /** The user of CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL, when the pod can see that URL. */
    migrateUser?: string
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

    /** Set when CREDENTIALS_SERVICE_KMS_PROVIDER is set. The integration routes need it. */
    kms?: KmsConfig

    /**
     * Set when CREDENTIALS_SERVICE_DATABASE_URL is set. Without it the service serves platform
     * secrets only, and the integration features are off.
     */
    database?: DatabaseConfig

    /**
     * Directory of Ed25519 public keys for the integrations audience, one `<deployment>.pub`
     * PEM file per caller. Unset means the service accepts no integrations token.
     */
    integrationCallerPublicKeysDir?: string
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

/** The database settings, or undefined when no database URL is set. */
export function loadDatabaseConfig(): DatabaseConfig | undefined {
    const url = process.env.CREDENTIALS_SERVICE_DATABASE_URL
    if (!url) {
        return undefined
    }
    const database: DatabaseConfig = { url, poolSize: intFromEnv('CREDENTIALS_SERVICE_DATABASE_POOL_SIZE', 20, 1) }
    const migrateUrl = process.env.CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL
    if (migrateUrl) {
        try {
            const migrateUser = decodeURIComponent(new URL(migrateUrl).username)
            if (migrateUser) {
                database.migrateUser = migrateUser
            }
        } catch {
            throw new Error('CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL is not a valid URL')
        }
    }
    return database
}

/**
 * What the migrate entry point needs. The migrate role owns the tables. The runtime role is the
 * one the service connects as, and gets grants from the migrations.
 */
export interface MigrateConfig {
    url: string
    /** Empty in single-role local development: the grants are then skipped. */
    runtimeRole: string
}

/** Prefers the migrate URL, and falls back to the runtime URL for single-role local development. */
export function loadMigrateConfig(): MigrateConfig | undefined {
    const url = process.env.CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL || process.env.CREDENTIALS_SERVICE_DATABASE_URL
    if (!url) {
        return undefined
    }
    const runtimeRole = process.env.CREDENTIALS_SERVICE_RUNTIME_ROLE ?? ''
    if (runtimeRole && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(runtimeRole)) {
        throw new Error(`CREDENTIALS_SERVICE_RUNTIME_ROLE is not a valid role name: ${JSON.stringify(runtimeRole)}`)
    }
    return { url, runtimeRole }
}

function kmsFromEnv(env: string): KmsConfig | undefined {
    const raw = process.env.CREDENTIALS_SERVICE_KMS_PROVIDER
    if (!raw) {
        return undefined
    }
    const provider = KMS_PROVIDERS.find((kind) => kind === raw)
    if (!provider) {
        throw new Error(
            `CREDENTIALS_SERVICE_KMS_PROVIDER must be one of ${KMS_PROVIDERS.join(', ')}, got ${JSON.stringify(raw)}`
        )
    }

    if (provider === 'local') {
        // The local keys sit in plain config, so they must never protect cloud customer data.
        if (isProductionEnv(env)) {
            throw new Error(`CREDENTIALS_SERVICE_KMS_PROVIDER=local is not allowed in ${env}`)
        }
        return { provider, keys: localKmsKeysFromEnv() }
    }

    const keyId = process.env.CREDENTIALS_SERVICE_KMS_KEY_ID
    if (!keyId) {
        throw new Error('CREDENTIALS_SERVICE_KMS_PROVIDER=aws needs CREDENTIALS_SERVICE_KMS_KEY_ID')
    }
    const config: AwsKmsConfig = { provider, keyId }
    const region = process.env.CREDENTIALS_SERVICE_KMS_REGION
    if (region) {
        config.region = region
    }
    const endpoint = process.env.CREDENTIALS_SERVICE_KMS_ENDPOINT
    if (endpoint) {
        config.endpoint = httpUrlFromEnv('CREDENTIALS_SERVICE_KMS_ENDPOINT', endpoint)
    }
    const proxyUrl = process.env.CREDENTIALS_SERVICE_KMS_PROXY_URL
    if (proxyUrl) {
        config.proxyUrl = httpUrlFromEnv('CREDENTIALS_SERVICE_KMS_PROXY_URL', proxyUrl)
    }
    return config
}

function localKmsKeysFromEnv(): Buffer[] {
    const raw = process.env.CREDENTIALS_SERVICE_KMS_LOCAL_KEYS
    if (!raw) {
        throw new Error('CREDENTIALS_SERVICE_KMS_PROVIDER=local needs CREDENTIALS_SERVICE_KMS_LOCAL_KEYS')
    }
    return raw.split(',').map((entry, index) => {
        const encoded = entry.trim()
        const key = Buffer.from(encoded, 'base64')
        // Buffer.from skips characters that are not base64, so compare the round trip to catch a
        // truncated or mistyped key. The message names the position only, never the value.
        if (key.length !== 32 || key.toString('base64') !== encoded) {
            throw new Error(`CREDENTIALS_SERVICE_KMS_LOCAL_KEYS entry ${index} is not a base64 32-byte key`)
        }
        return key
    })
}

function httpUrlFromEnv(key: string, raw: string): string {
    // The message leaves out the value: a proxy URL can carry a password.
    const url = URL.canParse(raw) ? new URL(raw) : null
    if (url?.protocol !== 'http:' && url?.protocol !== 'https:') {
        throw new Error(`${key} must be an http(s) URL`)
    }
    return raw
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

    const database = loadDatabaseConfig()
    if (database) {
        config.database = database
    }

    const integrationKeysDir = process.env.CREDENTIALS_SERVICE_INTEGRATION_CALLER_PUBLIC_KEYS_DIR
    if (integrationKeysDir) {
        config.integrationCallerPublicKeysDir = integrationKeysDir
    }

    if (secretSourceFromEnv() === 'kubernetes') {
        config.kubernetes = kubernetesFromEnv(serviceAccountDir)
    }

    const kms = kmsFromEnv(config.env)
    if (kms) {
        config.kms = kms
    }

    if (process.env.NODE_ENV === 'production' && !process.env.CREDENTIALS_SERVICE_ENV) {
        throw new Error('missing required configuration: CREDENTIALS_SERVICE_ENV')
    }

    return config
}
