import { Pool } from 'pg'
import { PluginsServer, PluginsServerConfig } from './types'
import { version } from '../package.json'
import { setupPlugins } from './plugins'
import { startWorker } from './worker'
import schedule, { Job } from 'node-schedule'
import Redis from 'ioredis'
import { startFastifyInstance, stopFastifyInstance } from './web/server'
import { FastifyInstance } from 'fastify'
import Worker from 'celery/worker'

export const defaultConfig: PluginsServerConfig = {
    CELERY_DEFAULT_QUEUE: 'celery',
    DATABASE_URL: 'postgres://localhost:5432/posthog',
    PLUGINS_CELERY_QUEUE: 'posthog-plugins',
    REDIS_URL: 'redis://localhost/',
    BASE_DIR: '.',
    PLUGINS_RELOAD_PUBSUB_CHANNEL: 'reload-plugins',
    DISABLE_WEB: false,
    WEB_PORT: 3008,
    WEB_HOSTNAME: '0.0.0.0',
}

export async function startPluginsServer(config: PluginsServerConfig): Promise<void> {
    console.info(`⚡ posthog-plugin-server v${version}`)

    let serverConfig: PluginsServerConfig | undefined
    let db: Pool | undefined
    let redis: Redis.Redis | undefined
    let pubSub: Redis.Redis | undefined
    let server: PluginsServer | undefined
    let fastifyInstance: FastifyInstance | undefined
    let worker: Worker | undefined
    let job: Job | undefined

    async function cleanUp() {
        console.info()
        if (fastifyInstance && !serverConfig?.DISABLE_WEB) {
            await stopFastifyInstance(fastifyInstance!)
        }
        await worker?.stop()
        pubSub?.disconnect()
        if (job) {
            schedule?.cancelJob(job)
        }
        await redis?.quit()
        await db?.end()
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, cleanUp)
    }

    try {
        serverConfig = {
            ...defaultConfig,
            ...config,
        }

        db = new Pool({
            connectionString: serverConfig.DATABASE_URL,
        })

        redis = new Redis(serverConfig.REDIS_URL)

        server = {
            ...serverConfig,
            db,
            redis,
        }

        await setupPlugins(server)

        if (!serverConfig.DISABLE_WEB) {
            fastifyInstance = await startFastifyInstance(serverConfig.WEB_PORT, serverConfig.WEB_HOSTNAME)
        }

        worker = startWorker(server)

        pubSub = new Redis(serverConfig.REDIS_URL)
        pubSub.subscribe(serverConfig.PLUGINS_RELOAD_PUBSUB_CHANNEL)
        pubSub.on('message', async (channel, message) => {
            if (channel === serverConfig!.PLUGINS_RELOAD_PUBSUB_CHANNEL) {
                console.log('Reloading plugins!')
                await worker!.stop()
                await setupPlugins(server!)
                worker = startWorker(server!)
            }
        })

        // every 5 sec set a @posthog-plugin-server/ping redis key
        job = schedule.scheduleJob('*/5 * * * * *', () => {
            redis!.set('@posthog-plugin-server/ping', new Date().toISOString())
            redis!.expire('@posthog-plugin-server/ping', 60)
        })
        console.info(`🚀 All systems go.`)
    } catch (error) {
        console.error(`💥 Launchpad failure!\n${error.stack}`)
        await cleanUp()
        process.exit(1)
    }
}
