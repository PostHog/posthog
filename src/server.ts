import { Pool } from 'pg'
import * as schedule from 'node-schedule'
import Redis from 'ioredis'
import { FastifyInstance } from 'fastify'
import { PluginConfigId, PluginsServer, PluginsServerConfig } from './types'
import { startQueue } from './worker/queue'
import { startFastifyInstance, stopFastifyInstance } from './web/server'
import { Worker } from 'celery/worker'
import { version } from '../package.json'
import { PluginEvent } from 'posthog-plugins'
import { defaultConfig } from './config'
import Piscina from 'piscina'
import * as Sentry from '@sentry/node'
import { delay } from './utils'
import { StatsD } from 'hot-shots'
import { processError } from './error'

export async function createServer(
    config: Partial<PluginsServerConfig> = {},
    threadId: number | null = null
): Promise<[PluginsServer, () => Promise<void>]> {
    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    const redis = new Redis(serverConfig.REDIS_URL, { maxRetriesPerRequest: -1 })
    redis.on('error', (error) => {
        Sentry.captureException(error)
        console.error('🔴 Redis error! Trying to reconnect.')
        console.error(error)
    })
    await redis.info()

    const db = new Pool({
        connectionString: serverConfig.DATABASE_URL,
    })

    let statsd: StatsD | undefined
    if (serverConfig.STATSD_HOST) {
        const statsd = new StatsD({
            port: serverConfig.STATSD_PORT,
            host: serverConfig.STATSD_HOST,
            prefix: serverConfig.STATSD_PREFIX,
        })
        // don't repeat the same info in each thread
        if (threadId === null) {
            console.info(
                `🪵 Sending metrics to statsd at ${serverConfig.STATSD_HOST}:${serverConfig.STATSD_PORT}, prefix: "${serverConfig.STATSD_PREFIX}"`
            )
        }
    }

    const server: PluginsServer = {
        ...serverConfig,
        db,
        redis,
        statsd,

        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        defaultConfigs: [],

        pluginSchedule: { runEveryMinute: [], runEveryHour: [], runEveryDay: [] },
        pluginSchedulePromises: { runEveryMinute: {}, runEveryHour: {}, runEveryDay: {} },
    }

    const closeServer = async () => {
        await server.redis.quit()
        await server.db.end()
    }

    return [server, closeServer]
}

export async function startPluginsServer(
    config: PluginsServerConfig,
    makePiscina: (config: PluginsServerConfig) => Piscina
): Promise<void> {
    console.info(`⚡ posthog-plugin-server v${version}`)

    let serverConfig: PluginsServerConfig | undefined
    let pubSub: Redis.Redis | undefined
    let server: PluginsServer | undefined
    let fastifyInstance: FastifyInstance | undefined
    let pingJob: schedule.Job | undefined
    let statsJob: schedule.Job | undefined
    let runEveryDayJob: schedule.Job | undefined
    let runEveryHourJob: schedule.Job | undefined
    let runEveryMinuteJob: schedule.Job | undefined
    let piscina: Piscina | undefined
    let queue: Worker | undefined
    let closeServer: () => Promise<void> | undefined

    let shutdownStatus = 0

    async function closeJobs(): Promise<void> {
        shutdownStatus += 1
        if (shutdownStatus === 2) {
            return console.info('🔁 Try again to shut down forcibly')
        }
        if (shutdownStatus >= 3) {
            console.info('❗️ Shutting down forcibly!')
            process.exit()
        }
        console.info('💤 Shutting down gracefully…')
        if (fastifyInstance && !serverConfig?.DISABLE_WEB) {
            await stopFastifyInstance(fastifyInstance!)
        }
        await queue?.stop()
        pubSub?.disconnect()
        pingJob && schedule.cancelJob(pingJob)
        statsJob && schedule.cancelJob(statsJob)
        runEveryDayJob && schedule.cancelJob(runEveryDayJob)
        runEveryHourJob && schedule.cancelJob(runEveryHourJob)
        runEveryMinuteJob && schedule.cancelJob(runEveryMinuteJob)
        await waitForTasksToFinish(server!)
        await stopPiscina(piscina!)
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
        const processEvent = (event: PluginEvent) => piscina!.runTask({ task: 'processEvent', args: { event } })

        if (!server.DISABLE_WEB) {
            fastifyInstance = await startFastifyInstance(server.WEB_PORT, server.WEB_HOSTNAME)
        }

        queue = startQueue(server, processEvent)

        pubSub = new Redis(server.REDIS_URL)
        pubSub.subscribe(server.PLUGINS_RELOAD_PUBSUB_CHANNEL)
        pubSub.on('message', async (channel, message) => {
            if (channel === server!.PLUGINS_RELOAD_PUBSUB_CHANNEL) {
                console.info('⚡ Reloading plugins!')
                await queue?.stop()
                await waitForTasksToFinish(server!)
                await stopPiscina(piscina!)
                piscina = makePiscina(serverConfig!)
                queue = startQueue(server!, processEvent)
                server!.pluginSchedule = await piscina.runTask({ task: 'getPluginSchedule' })
            }
        })

        // every 5 sec set a @posthog-plugin-server/ping redis key
        pingJob = schedule.scheduleJob('*/5 * * * * *', () => {
            server!.redis!.set('@posthog-plugin-server/ping', new Date().toISOString())
            server!.redis!.expire('@posthog-plugin-server/ping', 60)
        })

        // every 10 seconds sends stuff to statsd
        statsJob = schedule.scheduleJob('*/10 * * * * *', () => {
            if (piscina) {
                server!.statsd?.gauge(`piscina.utilization`, (piscina?.utilization || 0) * 100)
                server!.statsd?.gauge(`piscina.threads`, piscina?.threads.length)
                server!.statsd?.gauge(`piscina.queue_size`, piscina?.queueSize)
            }
        })

        server.pluginSchedule = await piscina.runTask({ task: 'getPluginSchedule' })

        runEveryMinuteJob = schedule.scheduleJob('* * * * *', () => {
            runTasksDebounced(server!, piscina!, 'runEveryMinute')
        })
        runEveryHourJob = schedule.scheduleJob('0 * * * *', () => {
            runTasksDebounced(server!, piscina!, 'runEveryHour')
        })
        runEveryDayJob = schedule.scheduleJob('0 0 * * *', () => {
            runTasksDebounced(server!, piscina!, 'runEveryDay')
        })

        console.info(`🚀 All systems go.`)
    } catch (error) {
        Sentry.captureException(error)
        console.error(`💥 Launchpad failure!\n${error.stack}`)
        Sentry.flush().then(() => true) // flush in the background
        await closeJobs()

        process.exit(1)
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait two seconds for any running workers to stop.
    // TODO: better "wait until everything is done"
    await delay(2000)
    await piscina.destroy()
}

export function runTasksDebounced(server: PluginsServer, piscina: Piscina, taskName: string) {
    const runTask = (pluginConfigId: PluginConfigId) => piscina.runTask({ task: taskName, args: { pluginConfigId } })

    for (const pluginConfigId of server.pluginSchedule[taskName]) {
        // last task still running? skip rerunning!
        if (server.pluginSchedulePromises[taskName][pluginConfigId]) {
            continue
        }

        const promise = runTask(pluginConfigId)
        server.pluginSchedulePromises[taskName][pluginConfigId] = promise

        promise
            .then(() => {
                server.pluginSchedulePromises[taskName][pluginConfigId] = null
            })
            .catch(async (error) => {
                await processError(server, pluginConfigId, error)
                server.pluginSchedulePromises[taskName][pluginConfigId] = null
            })
    }
}

export async function waitForTasksToFinish(server: PluginsServer) {
    const activePromises = Object.values(server.pluginSchedulePromises)
        .map(Object.values)
        .flat()
        .filter((a) => a)
    return Promise.all(activePromises)
}
