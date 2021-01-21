import { Pool } from 'pg'
import * as schedule from 'node-schedule'
import Redis from 'ioredis'
import { Kafka, logLevel } from 'kafkajs'
import { FastifyInstance } from 'fastify'
import { PluginsServer, PluginsServerConfig, Queue } from './types'
import { startQueue } from './worker/queue'
import { startFastifyInstance, stopFastifyInstance } from './web/server'
import { version } from '../package.json'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { defaultConfig } from './config'
import Piscina from 'piscina'
import * as Sentry from '@sentry/node'
import { delay } from './utils'
import { StatsD } from 'hot-shots'
import { EventsProcessor } from './ingestion/process-event'
import { status } from './status'
import { startSchedule } from './services/schedule'
import { ConnectionOptions } from 'tls'

export async function createServer(
    config: Partial<PluginsServerConfig> = {},
    threadId: number | null = null
): Promise<[PluginsServer, () => Promise<void>]> {
    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    const redis = new Redis(serverConfig.REDIS_URL, { maxRetriesPerRequest: -1 })
    redis
        .on('error', (error) => {
            Sentry.captureException(error)
            status.error('🔴', 'Redis error encountered! Trying to reconnect...\n', error)
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                status.info('✅', 'Connected to Redis!')
            }
        })
    await redis.info()

    const db = new Pool({
        connectionString: serverConfig.DATABASE_URL,
        ssl: process.env.DEPLOYMENT?.startsWith('Heroku')
            ? {
                  rejectUnauthorized: false,
              }
            : undefined,
    })

    let kafkaSsl: ConnectionOptions | undefined
    if (
        serverConfig.KAFKA_CLIENT_CERT_B64 &&
        serverConfig.KAFKA_CLIENT_CERT_KEY_B64 &&
        serverConfig.KAFKA_TRUSTED_CERT_B64
    ) {
        kafkaSsl = {
            cert: Buffer.from(serverConfig.KAFKA_CLIENT_CERT_B64, 'base64'),
            key: Buffer.from(serverConfig.KAFKA_CLIENT_CERT_KEY_B64, 'base64'),
            ca: Buffer.from(serverConfig.KAFKA_TRUSTED_CERT_B64, 'base64'),

            /* Intentionally disabling hostname checking. The Kafka cluster runs in the cloud and Apache
            Kafka on Heroku doesn't currently provide stable hostnames. We're pinned to a specific certificate
            #for this connection even though the certificate doesn't include host information. We rely
            on the ca trust_cert for this purpose. */
            rejectUnauthorized: false,
        }
    }

    let kafka: Kafka | undefined
    if (serverConfig.KAFKA_ENABLED) {
        if (!serverConfig.KAFKA_HOSTS) {
            throw new Error('You must set KAFKA_HOSTS to process events from Kafka!')
        }
        kafka = new Kafka({
            clientId: `plugin-server-v${version}`,
            brokers: serverConfig.KAFKA_HOSTS.split(','),
            logLevel: logLevel.NOTHING,
            ssl: kafkaSsl,
        })
    }

    let statsd: StatsD | undefined
    if (serverConfig.STATSD_HOST) {
        statsd = new StatsD({
            port: serverConfig.STATSD_PORT,
            host: serverConfig.STATSD_HOST,
            prefix: serverConfig.STATSD_PREFIX,
        })
        // don't repeat the same info in each thread
        if (threadId === null) {
            status.info(
                '🪵',
                `Sending metrics to StatsD at ${serverConfig.STATSD_HOST}:${serverConfig.STATSD_PORT}, prefix: "${serverConfig.STATSD_PREFIX}"`
            )
        }
    }

    const server: Omit<PluginsServer, 'eventsProcessor'> = {
        ...serverConfig,
        db,
        redis,
        kafka,
        statsd,
        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        defaultConfigs: [],

        pluginSchedule: { runEveryMinute: [], runEveryHour: [], runEveryDay: [] },
        pluginSchedulePromises: { runEveryMinute: {}, runEveryHour: {}, runEveryDay: {} },
    }

    server.eventsProcessor = new EventsProcessor(server as PluginsServer)

    const closeServer = async () => {
        await server.redis.quit()
        await server.db.end()
    }

    return [server as PluginsServer, closeServer]
}

// TODO: refactor this into a class, removing the need for many different Servers
type ServerInstance = {
    server: PluginsServer
    piscina: Piscina
    queue: Queue
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (config: PluginsServerConfig) => Piscina
): Promise<ServerInstance> {
    status.info('⚡', `posthog-plugin-server v${version}`)

    let serverConfig: PluginsServerConfig | undefined
    let pubSub: Redis.Redis | undefined
    let server: PluginsServer | undefined
    let fastifyInstance: FastifyInstance | undefined
    let pingJob: schedule.Job | undefined
    let statsJob: schedule.Job | undefined
    let piscina: Piscina | undefined
    let queue: Queue | undefined
    let closeServer: () => Promise<void> | undefined
    let stopSchedule: () => Promise<void> | undefined

    let shutdownStatus = 0

    async function closeJobs(): Promise<void> {
        shutdownStatus += 1
        if (shutdownStatus === 2) {
            status.info('🔁', 'Try again to shut down forcibly')
            return
        }
        if (shutdownStatus >= 3) {
            status.info('❗️', 'Shutting down forcibly!')
            piscina?.destroy()
            process.exit()
        }
        status.info('💤', ' Shutting down gracefully...')
        if (fastifyInstance && !serverConfig?.DISABLE_WEB) {
            await stopFastifyInstance(fastifyInstance!)
        }
        await queue?.stop()
        pubSub?.disconnect()
        pingJob && schedule.cancelJob(pingJob)
        statsJob && schedule.cancelJob(statsJob)
        await stopSchedule?.()
        if (piscina) {
            await stopPiscina(piscina)
        }
        await closeServer()

        // wait an extra second for any misc async task to finish
        await delay(1000)
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, closeJobs)
    }

    try {
        serverConfig = {
            ...defaultConfig,
            ...config,
        }
        ;[server, closeServer] = await createServer(serverConfig, null)

        piscina = makePiscina(serverConfig)
        const processEvent = (event: PluginEvent) => {
            if ((piscina?.queueSize || 0) > (server?.WORKER_CONCURRENCY || 4) * (server?.WORKER_CONCURRENCY || 4)) {
                queue?.pause()
            }
            return piscina!.runTask({ task: 'processEvent', args: { event } })
        }
        const processEventBatch = (batch: PluginEvent[]) => {
            if ((piscina?.queueSize || 0) > (server?.WORKER_CONCURRENCY || 4) * (server?.WORKER_CONCURRENCY || 4)) {
                queue?.pause()
            }
            return piscina!.runTask({ task: 'processEventBatch', args: { batch } })
        }

        if (!server.DISABLE_WEB) {
            fastifyInstance = await startFastifyInstance(server)
        }

        queue = await startQueue(server, processEvent, processEventBatch)
        piscina.on('drain', () => {
            queue?.resume()
        })

        pubSub = new Redis(server.REDIS_URL)
        pubSub.subscribe(server.PLUGINS_RELOAD_PUBSUB_CHANNEL)
        pubSub.on('message', async (channel: string, message) => {
            if (channel === server!.PLUGINS_RELOAD_PUBSUB_CHANNEL) {
                status.info('⚡', 'Reloading plugins!')
                await queue?.stop()
                await stopSchedule?.()
                if (piscina) {
                    await stopPiscina(piscina)
                }
                piscina = makePiscina(serverConfig!)
                queue = await startQueue(server!, processEvent, processEventBatch)
                stopSchedule = await startSchedule(server!, piscina)
            }
        })

        // every 5 seconds set a @posthog-plugin-server/ping Redis key
        pingJob = schedule.scheduleJob('*/5 * * * * *', () => {
            server!.redis!.set('@posthog-plugin-server/ping', new Date().toISOString())
            server!.redis!.expire('@posthog-plugin-server/ping', 60)
        })

        // every 10 seconds sends stuff to StatsD
        statsJob = schedule.scheduleJob('*/10 * * * * *', () => {
            if (piscina) {
                server!.statsd?.gauge(`piscina.utilization`, (piscina?.utilization || 0) * 100)
                server!.statsd?.gauge(`piscina.threads`, piscina?.threads.length)
                server!.statsd?.gauge(`piscina.queue_size`, piscina?.queueSize)
            }
        })

        stopSchedule = await startSchedule(server, piscina)

        status.info('🚀', 'All systems go.')
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', error)
        Sentry.flush().then(() => true) // flush in the background
        await closeJobs()
        process.exit(1)
    }

    return {
        server,
        piscina,
        queue,
        stop: closeJobs,
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait two seconds for any running workers to stop.
    // TODO: better "wait until everything is done"
    await delay(2000)
    await piscina.destroy()
}
