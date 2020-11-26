import { Pool } from 'pg'
import { PluginsServer, PluginsServerConfig } from './types'
import { version } from '../package.json'
import { setupPlugins } from './plugins'
import { startWorker } from './worker'
import schedule from 'node-schedule'
import Redis from 'ioredis'

const defaultConfig: PluginsServerConfig = {
    CELERY_DEFAULT_QUEUE: 'celery',
    DATABASE_URL: 'postgres://localhost:5432/posthog',
    PLUGINS_CELERY_QUEUE: 'posthog-plugins',
    REDIS_URL: 'redis://localhost/',
    BASE_DIR: '.',
    PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
}

export async function startPluginsServer(config: PluginsServerConfig): Promise<void> {
    console.info(`⚡ Starting posthog-plugin-server v${version}…`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    const db = new Pool({
        connectionString: serverConfig.DATABASE_URL,
    })
    const redis = new Redis(serverConfig.REDIS_URL)

    const server: PluginsServer = {
        ...serverConfig,
        db,
        redis,
    }

    await setupPlugins(server)
    startWorker(server)

    const pubSub = new Redis(serverConfig.REDIS_URL)
    pubSub.subscribe(serverConfig.PLUGINS_RELOAD_PUBSUB_CHANNEL)
    pubSub.on('message', (channel, message) => {
        if (channel === serverConfig.PLUGINS_RELOAD_PUBSUB_CHANNEL) {
            console.log('Reloading plugins!')
            setupPlugins(server)
        }
    })

    // every 5 sec set a @posthog-plugin-server/ping redis key
    schedule.scheduleJob('*/5 * * * * *', function () {
        redis.set('@posthog-plugin-server/ping', new Date().toISOString())
        redis.expire('@posthog-plugin-server/ping', 60)
    })

    console.info(`✅ Started posthog-plugin-server v${version}!`)
}
