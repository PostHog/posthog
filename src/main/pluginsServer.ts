import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { FastifyInstance } from 'fastify'
import Redis from 'ioredis'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../config/config'
import { JobQueueConsumerControl, PluginsServer, PluginsServerConfig, Queue, ScheduleControl } from '../types'
import { createServer } from '../utils/db/server'
import { killProcess } from '../utils/kill'
import { status } from '../utils/status'
import { createRedis, delay, getPiscinaStats } from '../utils/utils'
import { startQueue } from './ingestion-queues/queue'
import { startJobQueueConsumer } from './job-queues/job-queue-consumer'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'
import { startSchedule } from './services/schedule'
import { startFastifyInstance, stopFastifyInstance } from './services/web'

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
    let jobQueueConsumer: JobQueueConsumerControl | undefined
    let closeServer: () => Promise<void> | undefined
    let scheduleControl: ScheduleControl | undefined
    let mmdbServer: net.Server | undefined
    let lastActivityCheck: NodeJS.Timeout | undefined

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
        lastActivityCheck && clearInterval(lastActivityCheck)
        await queue?.stop()
        await pubSub?.quit()
        pingJob && schedule.cancelJob(pingJob)
        statsJob && schedule.cancelJob(statsJob)
        await jobQueueConsumer?.stop()
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
        jobQueueConsumer = await startJobQueueConsumer(server, piscina)

        queue = await startQueue(server, piscina)
        piscina.on('drain', () => {
            void queue?.resume()
            void jobQueueConsumer?.resume()
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
                for (const [key, value] of Object.entries(getPiscinaStats(piscina))) {
                    server!.statsd?.gauge(`piscina.${key}`, value)
                }
            }
        })

        if (serverConfig.STALENESS_RESTART_SECONDS > 0) {
            // check every 10 sec how long it has been since the last activity
            let lastFoundActivity: number
            lastActivityCheck = setInterval(() => {
                if (
                    server?.lastActivity &&
                    new Date().valueOf() - server?.lastActivity > serverConfig.STALENESS_RESTART_SECONDS * 1000 &&
                    lastFoundActivity !== server?.lastActivity
                ) {
                    lastFoundActivity = server?.lastActivity
                    const extra = {
                        instanceId: server.instanceId.toString(),
                        lastActivity: server.lastActivity ? new Date(server.lastActivity).toISOString() : null,
                        lastActivityType: server.lastActivityType,
                        piscina: piscina ? JSON.stringify(getPiscinaStats(piscina)) : null,
                    }
                    Sentry.captureMessage(
                        `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                        {
                            extra,
                        }
                    )
                    console.log(
                        `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                        extra
                    )
                    server.statsd?.increment(`alerts.stale_plugin_server_restarted`)

                    killProcess()
                }
            }, Math.min(serverConfig.STALENESS_RESTART_SECONDS, 10000))
        }

        serverInstance.piscina = piscina
        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        status.info('🚀', 'All systems go')

        server.lastActivity = new Date().valueOf()
        server.lastActivityType = 'serverStart'

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
