import { LogLevel, PluginsServerConfig } from './types'

export const defaultConfig = overrideWithEnv(getDefaultConfig())
export const configHelp = getConfigHelp()

export function getDefaultConfig(): PluginsServerConfig {
    return {
        CELERY_DEFAULT_QUEUE: 'celery',
        DATABASE_URL: 'postgres://localhost:5432/posthog',
        PLUGINS_CELERY_QUEUE: 'posthog-plugins',
        REDIS_URL: 'redis://localhost/',
        BASE_DIR: '.',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
        DISABLE_WEB: false,
        WEB_PORT: 3008,
        WEB_HOSTNAME: '0.0.0.0',
        WORKER_CONCURRENCY: 0, // use all cores
        TASKS_PER_WORKER: 10,
        LOG_LEVEL: LogLevel.Info,
        SENTRY_DSN: null,
        STATSD_HOST: null,
        STATSD_PORT: 8125,
        STATSD_PREFIX: 'plugin-server.',
    }
}

export function getConfigHelp(): Record<keyof PluginsServerConfig, string> {
    return {
        CELERY_DEFAULT_QUEUE: 'celery outgoing queue',
        DATABASE_URL: 'url for postgres',
        PLUGINS_CELERY_QUEUE: 'celery incoming queue',
        REDIS_URL: 'url for redis',
        BASE_DIR: 'base path for resolving local plugins',
        PLUGINS_RELOAD_PUBSUB_CHANNEL: 'redis channel for reload events',
        DISABLE_WEB: 'do not start the web service',
        WEB_PORT: 'port for web server',
        WEB_HOSTNAME: 'hostname for web server',
        WORKER_CONCURRENCY: 'number of concurrent worker threads',
        TASKS_PER_WORKER: 'number of parallel tasks per worker thread',
        LOG_LEVEL: 'minimum log level',
        SENTRY_DSN: 'sentry ingestion url',
        STATSD_HOST: 'StatsD host - integration disabled if not provided',
        STATSD_PORT: 'StatsD port',
        STATSD_PREFIX: 'StatsD prefix',
    }
}

export function overrideWithEnv(
    config: PluginsServerConfig,
    env: Record<string, string | undefined> = process.env
): PluginsServerConfig {
    const defaultConfig = getDefaultConfig()

    const newConfig: PluginsServerConfig = { ...config }
    for (const key of Object.keys(config)) {
        if (typeof env[key] !== 'undefined') {
            if (typeof defaultConfig[key] === 'number') {
                newConfig[key] = env[key]?.indexOf('.') ? parseFloat(env[key]!) : parseInt(env[key]!)
            } else if (typeof defaultConfig[key] === 'boolean') {
                newConfig[key] = env[key] === 'true' || env[key] === 'True' || env[key] === '1'
            } else {
                newConfig[key] = env[key]
            }
        }
    }
    return newConfig
}
