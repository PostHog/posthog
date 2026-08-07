// Typed accessor for process.env in the integration-service.
//
// KnownEnvKey is an exhaustive union of every environment variable the service
// reads. Callers use getEnv() instead of process.env[] directly so typos in key
// names are caught at compile time rather than silently returning undefined at
// runtime — which here would mean a security control quietly not applying.

export type KnownEnvKey =
    | 'PORT'
    | 'HOST'
    | 'NODE_ENV'
    | 'SHUTDOWN_GRACE_MS'
    | 'SHUTDOWN_PRESTOP_DELAY_MS'
    | 'INTEGRATION_SERVICE_LOG_LEVEL'
    | 'INTEGRATION_SERVICE_ENV'
    | 'INTEGRATION_SERVICE_REDIS_URL'
    | 'INTEGRATION_SERVICE_KMS_KEY_ID'
    | 'INTEGRATION_SERVICE_SECRET_ID'
    | 'INTEGRATION_SERVICE_CACHE_TTL_SECONDS'
    | 'INTEGRATION_SERVICE_DEK_ROTATION_SECONDS'
    | 'INTEGRATION_SERVICE_RETIRE_QUIET_HOURS'
    | 'INTEGRATION_SERVICE_USAGE_BUCKET'
    | 'INTEGRATION_SERVICE_USAGE_KMS_KEY_ID'
    | 'INTEGRATION_SERVICE_USAGE_PUBLISH_INTERVAL_MS'
    | 'INTEGRATION_SERVICE_METRICS_TOKEN'
    | 'AWS_REGION'
    | 'AWS_ENDPOINT_URL'

export function getEnv(key: KnownEnvKey): string | undefined {
    return process.env[key]
}
