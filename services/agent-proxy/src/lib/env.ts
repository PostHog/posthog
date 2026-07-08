// Typed accessor for process.env in the agent-proxy service.
//
// KnownEnvKey is an exhaustive union of every environment variable the service
// reads. Callers use getEnv() instead of process.env[] directly so typos in
// key names are caught at compile time rather than silently returning undefined
// at runtime.

export type KnownEnvKey =
    | 'TASKS_REDIS_URL'
    | 'SANDBOX_JWT_PUBLIC_KEY'
    | 'SANDBOX_JWT_PUBLIC_KEY_SECONDARY'
    | 'TASKS_AGENT_PROXY_CORS_ORIGINS'
    | 'AGENT_PROXY_DJANGO_CALLBACK_URL'
    | 'AGENT_PROXY_CALLBACK_SECRET'
    | 'AGENT_PROXY_MAX_CONCURRENT_STREAMS'
    | 'AGENT_PROXY_MAX_STREAMS_PER_RUN'
    | 'AGENT_PROXY_METRICS_TOKEN'
    | 'PORT'
    | 'HOST'
    | 'SHUTDOWN_GRACE_MS'
    | 'SHUTDOWN_PRESTOP_DELAY_MS'
    | 'NODE_ENV'
    | 'AGENT_PROXY_LOG_LEVEL'

export function getEnv(key: KnownEnvKey): string | undefined {
    return process.env[key]
}
