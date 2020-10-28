import { Pool } from 'pg'
import { PluginsServer, PluginsServerConfig } from './types'
import { version } from '../package.json'
import { setupPlugins } from './plugins'
import { startWorker } from './worker'
import Redis from 'ioredis'

const defaultConfig: PluginsServerConfig = {
    CELERY_DEFAULT_QUEUE: 'celery',
    DATABASE_URL: 'postgres://localhost:5432/posthog',
    PLUGINS_CELERY_QUEUE: 'posthog-plugins',
    REDIS_URL: 'redis://localhost/',
    BASE_DIR: '.',
}

export function startPluginsServer(config: PluginsServerConfig) {
    console.info(`⚡ Starting posthog-plugins server v${version}!`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    const db = new Pool({
        connectionString: serverConfig.DATABASE_URL,
    })
    const redis = new Redis(serverConfig.REDIS_URL) // uses defaults unless given configuration object

    const server: PluginsServer = {
        ...serverConfig,
        db,
        redis,
    }

    setupPlugins(server)
    startWorker(server)
}
