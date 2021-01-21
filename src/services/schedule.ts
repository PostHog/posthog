import { PluginConfigId, PluginsServer } from '../types'
import Piscina from 'piscina'
import { processError } from '../error'
import * as schedule from 'node-schedule'
import Redlock from 'redlock'
import * as Sentry from '@sentry/node'
import { status } from '../status'

const LOCKED_RESOURCE = 'plugin-server:locks:schedule'

export async function startSchedule(
    server: PluginsServer,
    piscina: Piscina,
    onLock?: () => void
): Promise<() => Promise<void>> {
    status.info('⏰', 'Starting scheduling service')

    let stopped = false
    let weHaveTheLock = false
    let lock: Redlock.Lock
    let lockTimeout: NodeJS.Timeout

    const lockTTL = server.SCHEDULE_LOCK_TTL * 1000 // 60 sec
    const retryDelay = lockTTL / 10 // 6 sec
    const extendDelay = lockTTL / 2 // 30 sec

    const redlock = new Redlock([server.redis], {
        // we handle retires ourselves to have a way to cancel the promises on quit
        // without this, the `await redlock.lock()` code will remain inflight and cause issues
        retryCount: 0,
    })

    redlock.on('clientError', (error) => {
        if (stopped) {
            return
        }
        status.error('🔴', 'Redlock client error occurred:\n', error)
        Sentry.captureException(error)
    })

    const tryToGetTheLock = async () => {
        try {
            lock = await redlock.lock(LOCKED_RESOURCE, lockTTL)
            weHaveTheLock = true

            status.info('🔒', 'Scheduler lock acquired!')

            const extendLock = async () => {
                if (stopped) {
                    return
                }
                try {
                    lock = await lock.extend(lockTTL)
                    lockTimeout = setTimeout(extendLock, extendDelay)
                } catch (error) {
                    status.error('🔴', 'Redlock cannot extend lock:\n', error)
                    Sentry.captureException(error)
                    weHaveTheLock = false
                    lockTimeout = setTimeout(tryToGetTheLock, 0)
                }
            }

            lockTimeout = setTimeout(extendLock, extendDelay)

            onLock?.()
        } catch (error) {
            if (stopped) {
                return
            }
            weHaveTheLock = false
            if (error instanceof Redlock.LockError) {
                lockTimeout = setTimeout(tryToGetTheLock, retryDelay)
            } else {
                Sentry.captureException(error)
                status.error('🔴', 'Redlock error:\n', error)
            }
        }
    }

    lockTimeout = setTimeout(tryToGetTheLock, 0)

    server.pluginSchedule = await piscina.runTask({ task: 'getPluginSchedule' })

    const runEveryMinuteJob = schedule.scheduleJob('* * * * *', () => {
        !stopped && weHaveTheLock && runTasksDebounced(server!, piscina!, 'runEveryMinute')
    })
    const runEveryHourJob = schedule.scheduleJob('0 * * * *', () => {
        !stopped && weHaveTheLock && runTasksDebounced(server!, piscina!, 'runEveryHour')
    })
    const runEveryDayJob = schedule.scheduleJob('0 0 * * *', () => {
        !stopped && weHaveTheLock && runTasksDebounced(server!, piscina!, 'runEveryDay')
    })

    const stopSchedule = async () => {
        stopped = true
        lockTimeout && clearTimeout(lockTimeout)
        runEveryDayJob && schedule.cancelJob(runEveryDayJob)
        runEveryHourJob && schedule.cancelJob(runEveryHourJob)
        runEveryMinuteJob && schedule.cancelJob(runEveryMinuteJob)

        await lock?.unlock().catch(Sentry.captureException)
        await waitForTasksToFinish(server!)
    }

    return stopSchedule
}

export function runTasksDebounced(server: PluginsServer, piscina: Piscina, taskName: string): void {
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

export async function waitForTasksToFinish(server: PluginsServer): Promise<any[]> {
    const activePromises = Object.values(server.pluginSchedulePromises)
        .map(Object.values)
        .flat()
        .filter((a) => a)
    return Promise.all(activePromises)
}
