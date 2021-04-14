import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { FastifyInstance } from 'fastify'
import Redis from 'ioredis'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../shared/config'
import { createServer } from '../shared/server'
import { status } from '../shared/status'
import { createRedis, delay } from '../shared/utils'
import { PluginsServer, PluginsServerConfig, Queue, ScheduleControl } from '../types'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './mmdb'
import { startQueue } from './queue'
import { startSchedule } from './services/schedule'
import { startFastifyInstance, stopFastifyInstance } from './web/server'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    server: PluginsServer
    piscina: Piscina
    queue: Queue
    mmdb?: ReaderModel
    mmdbUpdateJob?: schedule.Job
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
    let mmdbServer: net.Server | undefined

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
        await new Promise<void>((resolve, reject) =>
            !mmdbServer
                ? resolve()
                : mmdbServer.close((error) => {
                      if (error) {
                          reject(error)
                      } else {
                          status.info('🛑', 'Closed internal MMDB server!')
                          resolve()
                      }
                  })
        )
        if (piscina) {
            await stopPiscina(piscina)
        }
        await closeServer?.()
        status.info('👋', 'Over and out!')
        // wait an extra second for any misc async task to finish
        await delay(1000)
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        await closeJobs()
        process.exit(0)
    })

    try {
        ;[server, closeServer] = await createServer(serverConfig, null)

        const serverInstance: Partial<ServerInstance> & Pick<ServerInstance, 'server'> = {
            server,
        }

        if (!serverConfig.DISABLE_MMDB) {
            serverInstance.mmdb = (await prepareMmdb(serverInstance)) ?? undefined
            serverInstance.mmdbUpdateJob = schedule.scheduleJob(
                '0 */4 * * *',
                async () => await performMmdbStalenessCheck(serverInstance)
            )
            mmdbServer = await createMmdbServer(serverInstance)
            serverConfig.INTERNAL_MMDB_SERVER_PORT = (mmdbServer.address() as AddressInfo).port
            server.INTERNAL_MMDB_SERVER_PORT = serverConfig.INTERNAL_MMDB_SERVER_PORT
        }

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

        serverInstance.piscina = piscina
        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        status.info('🚀', 'All systems go')

        return serverInstance as ServerInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', error)
        void Sentry.flush() // flush in the background
        await closeJobs()
        process.exit(1)
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait *up to* 5 seconds to shut down VMs.
    await Promise.race([piscina.broadcastTask({ task: 'teardownPlugins' }), delay(5000)])
    // Wait 2 seconds to flush the last queues.
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
    await piscina.destroy()
}
