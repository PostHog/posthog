// Typed accessor for process.env. Callers use getEnv() instead of process.env[] so a typo
// in a key name fails at compile time rather than silently returning undefined, which here
// would mean a security control quietly not applying.

export type KnownEnvKey =
    | 'PORT'
    | 'HOST'
    | 'NODE_ENV'
    | 'SHUTDOWN_GRACE_MS'
    | 'SHUTDOWN_PRESTOP_DELAY_MS'
    | 'INTEGRATION_SERVICE_LOG_LEVEL'
    | 'INTEGRATION_SERVICE_ENV'
    | 'INTEGRATION_SERVICE_SECRETS_DIR'
    | 'INTEGRATION_SERVICE_DATABASE_URL'
    | 'INTEGRATION_SERVICE_RELOAD_SECONDS'
    | 'INTEGRATION_SERVICE_USAGE_FLUSH_MS'
    | 'INTEGRATION_SERVICE_RETENTION_DAYS'
    | 'INTEGRATION_SERVICE_RETIRE_QUIET_HOURS'
    | 'INTEGRATION_SERVICE_METRICS_TOKEN'

export function getEnv(key: KnownEnvKey): string | undefined {
    return process.env[key]
}
