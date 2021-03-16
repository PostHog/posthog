import ClickHouse from '@posthog/clickhouse'
import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { FastifyInstance } from 'fastify'
import * as fs from 'fs'
import { createPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import Redis from 'ioredis'
import { Kafka, logLevel, Producer } from 'kafkajs'
import { DateTime } from 'luxon'
import * as schedule from 'node-schedule'
import * as path from 'path'
import { Pool, types as pgTypes } from 'pg'
import Piscina from 'piscina'
import { ConnectionOptions } from 'tls'

import { defaultConfig } from './config'
import { DB } from './db'
import { EventsProcessor } from './ingestion/process-event'
import { startSchedule } from './services/schedule'
import { status } from './status'
import { PluginsServer, PluginsServerConfig, Queue, ScheduleControl } from './types'
import { createPostgresPool, createRedis, delay, UUIDT } from './utils'
import { startFastifyInstance, stopFastifyInstance } from './web/server'
import { startQueue } from './worker/queue'

const { version } = require('../package.json')

export async function createServer(
    config: Partial<PluginsServerConfig> = {},
    threadId: number | null = null
): Promise<[PluginsServer, () => Promise<void>]> {
    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

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

    let clickhouse: ClickHouse | undefined
    let kafka: Kafka | undefined
    let kafkaProducer: Producer | undefined
    if (serverConfig.KAFKA_ENABLED) {
        if (!serverConfig.KAFKA_HOSTS) {
            throw new Error('You must set KAFKA_HOSTS to process events from Kafka!')
        }
        clickhouse = new ClickHouse({
            host: serverConfig.CLICKHOUSE_HOST,
            port: serverConfig.CLICKHOUSE_SECURE ? 8443 : 8123,
            protocol: serverConfig.CLICKHOUSE_SECURE ? 'https:' : 'http:',
            user: serverConfig.CLICKHOUSE_USER,
            password: serverConfig.CLICKHOUSE_PASSWORD || undefined,
            dataObjects: true,
            queryOptions: {
                database: serverConfig.CLICKHOUSE_DATABASE,
                output_format_json_quote_64bit_integers: false,
            },
            ca: serverConfig.CLICKHOUSE_CA
                ? fs.readFileSync(path.join(serverConfig.BASE_DIR, serverConfig.CLICKHOUSE_CA)).toString()
                : undefined,
            rejectUnauthorized: serverConfig.CLICKHOUSE_CA ? false : undefined,
        })
        await clickhouse.querying('SELECT 1') // test that the connection works

        kafka = new Kafka({
            clientId: `plugin-server-v${version}-${new UUIDT()}`,
            brokers: serverConfig.KAFKA_HOSTS.split(','),
            logLevel: logLevel.WARN,
            ssl: kafkaSsl,
        })
        kafkaProducer = kafka.producer()
        await kafkaProducer?.connect()
    }

    // `node-postgres` will return dates as plain JS Date objects, which will use the local timezone.
    // This converts all date fields to a proper luxon UTC DateTime and then casts them to a string
    // Unfortunately this must be done on a global object before initializing the `Pool`
    pgTypes.setTypeParser(1083 /* types.TypeId.TIME */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )
    pgTypes.setTypeParser(1114 /* types.TypeId.TIMESTAMP */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )
    pgTypes.setTypeParser(1184 /* types.TypeId.TIMESTAMPTZ */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )

    const postgres = createPostgresPool(serverConfig)

    const redisPool = createPool<Redis.Redis>(
        {
            create: () => createRedis(serverConfig),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: serverConfig.REDIS_POOL_MIN_SIZE,
            max: serverConfig.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )

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

    const db = new DB(postgres, redisPool, kafkaProducer, clickhouse, statsd)

    const server: Omit<PluginsServer, 'eventsProcessor'> = {
        ...serverConfig,
        db,
        postgres,
        redisPool,
        clickhouse,
        kafka,
        kafkaProducer,
        statsd,
        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),

        pluginSchedule: null,
        pluginSchedulePromises: { runEveryMinute: {}, runEveryHour: {}, runEveryDay: {} },
    }

    server.eventsProcessor = new EventsProcessor(server as PluginsServer)

    const closeServer = async () => {
        await kafkaProducer?.disconnect()
        await redisPool.drain()
        await redisPool.clear()
        await server.postgres.end()
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
    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.info('⚡', `posthog-plugin-server v${version}`)
    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)

    let pubSub: Redis.Redis | undefined
    let server: PluginsServer | undefined
    let fastifyInstance: FastifyInstance | undefined
    let pingJob: schedule.Job | undefined
    let statsJob: schedule.Job | undefined
    let piscina: Piscina | undefined
    let queue: Queue | undefined
    let closeServer: () => Promise<void> | undefined
    let scheduleControl: ScheduleControl | undefined

    let shutdownStatus = 0

    async function closeJobs(): Promise<void> {
        shutdownStatus += 1
        if (shutdownStatus === 2) {
            status.info('🔁', 'Try again to shut down forcibly')
            return
        }
        if (shutdownStatus >= 3) {
            status.info('❗️', 'Shutting down forcibly!')
            void piscina?.destroy()
            process.exit()
        }
        status.info('💤', ' Shutting down gracefully...')
        if (fastifyInstance && !serverConfig?.DISABLE_WEB) {
            await stopFastifyInstance(fastifyInstance!)
        }
        await queue?.stop()
        await pubSub?.quit()
        pingJob && schedule.cancelJob(pingJob)
        statsJob && schedule.cancelJob(statsJob)
        await scheduleControl?.stopSchedule()
        if (piscina) {
            await stopPiscina(piscina)
        }
        await closeServer?.()

        // wait an extra second for any misc async task to finish
        await delay(1000)
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, closeJobs)
    }

    try {
        ;[server, closeServer] = await createServer(serverConfig, null)

        piscina = makePiscina(serverConfig)
        if (!server.DISABLE_WEB) {
            fastifyInstance = await startFastifyInstance(server)
        }

        scheduleControl = await startSchedule(server, piscina)
        queue = await startQueue(server, piscina)
        piscina.on('drain', () => {
            queue?.resume()
        })

        // use one extra connection for redis pubsub
        pubSub = await createRedis(server)
        await pubSub.subscribe(server.PLUGINS_RELOAD_PUBSUB_CHANNEL)
        pubSub.on('message', async (channel: string, message) => {
            if (channel === server!.PLUGINS_RELOAD_PUBSUB_CHANNEL) {
                status.info('⚡', 'Reloading plugins!')

                await piscina?.broadcastTask({ task: 'reloadPlugins' })
                await scheduleControl?.reloadSchedule()
            }
        })

        // every 5 seconds set Redis keys @posthog-plugin-server/ping and @posthog-plugin-server/version
        pingJob = schedule.scheduleJob('*/5 * * * * *', async () => {
            await server!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, false)
            await server!.db!.redisSet('@posthog-plugin-server/version', version, undefined, false)
        })

        // every 10 seconds sends stuff to StatsD
        statsJob = schedule.scheduleJob('*/10 * * * * *', () => {
            if (piscina) {
                server!.statsd?.gauge(`piscina.utilization`, (piscina?.utilization || 0) * 100)
                server!.statsd?.gauge(`piscina.threads`, piscina?.threads.length)
                server!.statsd?.gauge(`piscina.queue_size`, piscina?.queueSize)
            }
        })

        status.info('🚀', 'All systems go.')
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', error)
        void Sentry.flush() // flush in the background
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
