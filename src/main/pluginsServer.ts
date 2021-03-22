import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { FastifyInstance } from 'fastify'
import Redis from 'ioredis'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../shared/config'
import { createServer } from '../shared/server'
import { status } from '../shared/status'
import { createRedis, delay } from '../shared/utils'
import { PluginsServer, PluginsServerConfig, Queue, ScheduleControl } from '../types'
import { startQueue } from './queue'
import { startSchedule } from './services/schedule'
import { startFastifyInstance, stopFastifyInstance } from './web/server'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
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
            await server!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, {
                jsonSerialize: false,
            })
            await server!.db!.redisSet('@posthog-plugin-server/version', version, undefined, { jsonSerialize: false })
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
    await Promise.race([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
    await piscina.destroy()
}
