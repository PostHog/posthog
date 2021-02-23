import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import Client from '../../src/celery/client'
import { startPluginsServer } from '../../src/server'
import { LogLevel } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabase } from '../helpers/sql'
import { setupPiscina } from '../helpers/worker'

jest.mock('../../src/sql')
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
    const getPluginSchedule = () => piscina.runTask({ task: 'getPluginSchedule' })
    const ingestEvent = (event: PluginEvent) => piscina.runTask({ task: 'ingestEvent', args: { event } })

    const pluginSchedule = await getPluginSchedule()
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
            PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
            CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
            LOG_LEVEL: LogLevel.Debug,
        },
        makePiscina
    )

    const redis = await pluginsServer.server.redisPool.acquire()

    await redis.del(pluginsServer.server.PLUGINS_CELERY_QUEUE)
    await redis.del(pluginsServer.server.CELERY_DEFAULT_QUEUE)

    const kwargs = {
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
    }
    const args = Object.values(kwargs)

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
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 2)
    expect(pluginsServer.queue.isPaused()).toBe(false)

    // 2 tasks * 2 threads = 4 active
    // 2 threads * 2 threads = 4 queue excess
    for (let i = 0; i < 50; i++) {
        client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    }

    for (let i = 0; i < 50; i++) {
        if ((await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)) > 40) {
            await delay(100)
        }
    }

    expect(await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)).toBe(40)
    expect(await redis.llen(pluginsServer.server.CELERY_DEFAULT_QUEUE)).toBe(2)

    await delay(100)

    expect(pluginsServer.queue.isPaused()).toBe(true)
    expect(pluginsServer.piscina.queueSize).toBe(6)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 2)

    for (let i = 0; i < 50; i++) {
        if ((await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)) > 32) {
            await delay(100)
        }
    }

    expect(await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)).toBe(32)
    expect(await redis.llen(pluginsServer.server.CELERY_DEFAULT_QUEUE)).toBe(10)

    expect(pluginsServer.queue.isPaused()).toBe(true)
    expect(pluginsServer.piscina.queueSize).toBe(6)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 10)

    await delay(1000)

    expect(await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)).toBe(32)
    expect(await redis.llen(pluginsServer.server.CELERY_DEFAULT_QUEUE)).toBe(14)

    expect(pluginsServer.queue.isPaused()).toBe(true)
    expect(pluginsServer.piscina.queueSize).toBe(2)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 14)

    await delay(10000)

    expect(pluginsServer.queue.isPaused()).toBe(false)
    expect(pluginsServer.piscina.queueSize).toBe(0)
    expect(pluginsServer.piscina.completed).toBe(baseCompleted + 52)

    expect(await redis.llen(pluginsServer.server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await redis.llen(pluginsServer.server.CELERY_DEFAULT_QUEUE)).toBe(52)

    await pluginsServer.server.redisPool.release(redis)
    await pluginsServer.stop()
})
