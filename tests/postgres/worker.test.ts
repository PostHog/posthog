import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import Client from '../../src/celery/client'
import { startPluginsServer } from '../../src/server'
import { loadPluginSchedule } from '../../src/services/schedule'
import { LogLevel } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabase } from '../helpers/sql'
import { setupPiscina } from '../helpers/worker'

jest.mock('../../src/sql')
jest.mock('../../src/status')
jest.setTimeout(600000) // 600 sec timeout

function createEvent(index = 0): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
    }
}

beforeEach(() => {
    console.debug = jest.fn()
})

test('piscina worker test', async () => {
    const workerThreads = 2
    const testCode = `
        function processEvent (event, meta) {
            event.properties["somewhere"] = "over the rainbow";
            return event
        }
        async function runEveryDay (meta) {
            return 4
        }
    `
    await resetTestDatabase(testCode)
    const piscina = setupPiscina(workerThreads, 10)

    const processEvent = (event: PluginEvent) => piscina.runTask({ task: 'processEvent', args: { event } })
    const processEventBatch = (batch: PluginEvent[]) => piscina.runTask({ task: 'processEventBatch', args: { batch } })
    const runEveryDay = (pluginConfigId: number) => piscina.runTask({ task: 'runEveryDay', args: { pluginConfigId } })
    const ingestEvent = (event: PluginEvent) => piscina.runTask({ task: 'ingestEvent', args: { event } })

    const pluginSchedule = await loadPluginSchedule(piscina)
    expect(pluginSchedule).toEqual({ runEveryDay: [39], runEveryHour: [], runEveryMinute: [] })

    const event = await processEvent(createEvent())
    expect(event.properties['somewhere']).toBe('over the rainbow')

    const eventBatch = await processEventBatch([createEvent()])
    expect(eventBatch[0]!.properties['somewhere']).toBe('over the rainbow')

    const everyDayReturn = await runEveryDay(39)
    expect(everyDayReturn).toBe(4)

    const ingestResponse1 = await ingestEvent(createEvent())
    expect(ingestResponse1).toEqual({ error: 'Not a valid UUID: "undefined"' })

    const ingestResponse2 = await ingestEvent({ ...createEvent(), uuid: new UUIDT().toString() })
    expect(ingestResponse2).toEqual({ success: true })

    await piscina.destroy()
})

test('assume that the workerThreads and tasksPerWorker values behave as expected', async () => {
    const workerThreads = 2
    const tasksPerWorker = 3
    const testCode = `
        async function processEvent (event, meta) {
            await new Promise(resolve => __jestSetTimeout(resolve, 300))
            return event
        }
    `
    await resetTestDatabase(testCode)
    const piscina = setupPiscina(workerThreads, tasksPerWorker)
    const processEvent = (event: PluginEvent) => piscina.runTask({ task: 'processEvent', args: { event } })
    const promises = []

    // warmup 2x
    await Promise.all([processEvent(createEvent()), processEvent(createEvent())])

    // process 10 events in parallel and ignore the result
    for (let i = 0; i < 10; i++) {
        promises.push(processEvent(createEvent(i)))
    }
    await delay(100)
    expect(piscina.queueSize).toBe(10 - workerThreads * tasksPerWorker)
    expect(piscina.completed).toBe(0 + 2)
    await delay(300)
    expect(piscina.queueSize).toBe(0)
    expect(piscina.completed).toBe(workerThreads * tasksPerWorker + 2)
    await delay(300)
    expect(piscina.queueSize).toBe(0)
    expect(piscina.completed).toBe(10 + 2)

    await piscina.destroy()
})

test('pause the queue if too many tasks', async () => {
    const testCode = `
        async function processEvent (event) {
            await new Promise(resolve => __jestSetTimeout(resolve, 1000))
            return event
        }
    `
    await resetTestDatabase(testCode)
    const pluginsServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 2,
            TASKS_PER_WORKER: 2,
            REDIS_POOL_MIN_SIZE: 3,
            REDIS_POOL_MAX_SIZE: 3,
            PLUGINS_CELERY_QUEUE: `test-plugins-celery-queue-${new UUIDT()}`,
            CELERY_DEFAULT_QUEUE: `test-celery-default-queue-${new UUIDT()}`,
            LOG_LEVEL: LogLevel.Debug,
        },
        makePiscina
    )

    const redis = await pluginsServer.server.redisPool.acquire()

    await redis.del(pluginsServer.server.PLUGINS_CELERY_QUEUE)
    await redis.del(pluginsServer.server.CELERY_DEFAULT_QUEUE)

    const args = Object.values({
        distinct_id: 'my-id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        data: {
            event: '$pageview',
            properties: {},
        },
        team_id: 2,
        now: new Date().toISOString(),
        sent_at: new Date().toISOString(),
        uuid: new UUIDT().toString(),
    })

    const baseCompleted = pluginsServer.piscina.completed

    expect(pluginsServer.piscina.queueSize).toBe(0)

    const client = new Client(pluginsServer.server.db, pluginsServer.server.PLUGINS_CELERY_QUEUE)
    for (let i = 0; i < 2; i++) {
        client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    }

    await delay(100)

    expect(pluginsServer.piscina.queueSize).toBe(0)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted)
    expect(pluginsServer.queue.isPaused()).toBe(false)

    await delay(5000)

    expect(pluginsServer.piscina.queueSize).toBe(0)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 4)
    expect(pluginsServer.queue.isPaused()).toBe(false)

    // 2 tasks * 2 threads = 4 active
    // 2 threads * 2 threads = 4 queue excess
    for (let i = 0; i < 50; i++) {
        client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    }

    let celerySize = 50,
        pausedTimes = 0
    const startTime = pluginsServer.piscina.duration
    while (celerySize > 0 || pluginsServer.piscina.queueSize > 0) {
        await delay(50)
        celerySize = await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)

        if (pluginsServer.queue.isPaused()) {
            pausedTimes++
            expect(pluginsServer.piscina.queueSize).toBeGreaterThan(0)
        }
    }

    await delay(3000)

    expect(pausedTimes).toBeGreaterThanOrEqual(10)
    expect(pluginsServer.queue.isPaused()).toBe(false)
    expect(pluginsServer.piscina.queueSize).toBe(0)
    expect(pluginsServer.piscina.completed).toEqual(baseCompleted + 104)

    const duration = pluginsServer.piscina.duration - startTime
    const expectedTimeMs = (50 / 4) * 1000

    expect(duration).toBeGreaterThanOrEqual(expectedTimeMs)
    expect(duration).toBeLessThanOrEqual(expectedTimeMs * 1.4)

    await pluginsServer.server.redisPool.release(redis)
    await pluginsServer.stop()
})
