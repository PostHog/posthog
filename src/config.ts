import { PluginsServerConfig } from './types'

export const defaultConfig = overrideWithEnv(getDefaultConfig())
export const configHelp = getConfigHelp()

function getDefaultConfig(): PluginsServerConfig {
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
        TASKS_PER_WORKER: 1,
        LOG_LEVEL: 'log',
    }
}

function getConfigHelp(): Record<string, string> {
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
    }
}

function overrideWithEnv(config: PluginsServerConfig): PluginsServerConfig {
    const newConfig: Record<string, any> = { ...config }
    for (const [key, value] of Object.entries(config)) {
        if (process.env[key]) {
            newConfig[key] = process.env[key]
        }
    }
    return newConfig as PluginsServerConfig
}
