import Client from '../../src/celery/client'
import { runPlugins } from '../../src/plugins'
import { createServer } from '../../src/server'
import { LogLevel, PluginsServer } from '../../src/types'
import { delay } from '../../src/utils'
import { startQueue } from '../../src/worker/queue'

jest.setTimeout(60000) // 60 sec timeout

function advanceOneTick() {
    return new Promise((resolve) => process.nextTick(resolve))
}

async function getServer(): Promise<[PluginsServer, () => Promise<void>]> {
    const [server, stopServer] = await createServer({
        REDIS_POOL_MIN_SIZE: 3,
        REDIS_POOL_MAX_SIZE: 3,
        PLUGINS_CELERY_QUEUE: 'ttt-test-plugins-celery-queue',
        CELERY_DEFAULT_QUEUE: 'ttt-test-celery-default-queue',
        PLUGIN_SERVER_INGESTION: false,
        LOG_LEVEL: LogLevel.Log,
    })

    const redis = await server.redisPool.acquire()
    await redis.del(server.PLUGINS_CELERY_QUEUE)
    await redis.del(server.CELERY_DEFAULT_QUEUE)
    await server.redisPool.release(redis)
    return [server, stopServer]
}

test('worker and task passing via redis', async () => {
    const [server, stopServer] = await getServer()
    const redis = await server.redisPool.acquire()
    // Nothing in the redis queue
    const queue1 = await redis.llen(server.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(0)

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

    // Tricky: make a client to the PLUGINS_CELERY_QUEUE queue (not CELERY_DEFAULT_QUEUE as normally)
    // This is so that the worker can directly read from it. Basically we will simulate a event sent from posthog.
    const client = new Client(server.db, server.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    await delay(1000)

    const queue2 = await redis.llen(server.PLUGINS_CELERY_QUEUE)
    expect(queue2).toBe(1)

    const item2 = await redis.lpop(server.PLUGINS_CELERY_QUEUE)
    await redis.lpush(server.PLUGINS_CELERY_QUEUE, item2)
    const item = JSON.parse(item2)

    expect(item['content-type']).toBe('application/json')
    expect(item['headers']['lang']).toBe('js')
    expect(item['headers']['task']).toBe('posthog.tasks.process_event.process_event_with_plugins')
    expect(item['properties']['body_encoding']).toBe('base64')

    const body = Buffer.from(item['body'], 'base64').toString()
    const [args2, kwargs2] = JSON.parse(body)

    expect(args2).toEqual(args)
    expect(kwargs2).toEqual({})

    const queue = await startQueue(server, undefined, {
        processEvent: (event) => runPlugins(server, event),
        processEventBatch: (events) => Promise.all(events.map((event) => runPlugins(server, event))),
        ingestEvent: () => Promise.resolve({ success: true }),
    })

    await delay(100)

    // get the new processed task from CELERY_DEFAULT_QUEUE
    const queue3 = await redis.llen(server.CELERY_DEFAULT_QUEUE)
    expect(queue3).toBe(1)
    const item3 = await redis.lpop(server.CELERY_DEFAULT_QUEUE)
    await redis.lpush(server.CELERY_DEFAULT_QUEUE, item3)
    const processedItem = JSON.parse(item3)

    expect(processedItem['content-type']).toBe('application/json')
    expect(processedItem['headers']['lang']).toBe('js')
    expect(processedItem['headers']['task']).toBe('posthog.tasks.process_event.process_event')
    expect(processedItem['properties']['body_encoding']).toBe('base64')

    const processedBody = Buffer.from(processedItem['body'], 'base64').toString()
    const [args3, kwargs3] = JSON.parse(processedBody)

    expect(args3).toEqual([])
    expect(kwargs3).toEqual(kwargs)

    await queue.stop()
    await server.redisPool.release(redis)
    await stopServer()
})

test('process multiple tasks', async () => {
    const [server, stopServer] = await getServer()
    const redis = await server.redisPool.acquire()
    // Nothing in the redis queue
    const queue1 = await redis.llen(server.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(0)

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

    // Tricky: make a client to the PLUGINS_CELERY_QUEUE queue (not CELERY_DEFAULT_QUEUE as normally)
    // This is so that the worker can directly read from it. Basically we will simulate a event sent from posthog.
    const client = new Client(server.db, server.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    await delay(1000)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    const queue = await startQueue(server, undefined, {
        processEvent: async (event) => runPlugins(server, event),
        processEventBatch: (events) => Promise.all(events.map((event) => runPlugins(server, event))),
        ingestEvent: () => Promise.resolve({ success: true }),
    })

    await delay(1000)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    const oneTask = await redis.lpop(server.CELERY_DEFAULT_QUEUE)
    expect(JSON.parse(oneTask)['headers']['lang']).toBe('js')

    await queue.stop()
    await server.redisPool.release(redis)
    await stopServer()
})

test('pause and resume queue', async () => {
    const [server, stopServer] = await getServer()
    const redis = await server.redisPool.acquire()
    // Nothing in the redis queue
    const queue1 = await redis.llen(server.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(0)

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

    // Tricky: make a client to the PLUGINS_CELERY_QUEUE queue (not CELERY_DEFAULT_QUEUE as normally)
    // This is so that the worker can directly read from it. Basically we will simulate a event sent from posthog.
    const client = new Client(server.db, server.PLUGINS_CELERY_QUEUE)
    for (let i = 0; i < 6; i++) {
        client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    }

    await delay(1000)

    // There'll be a "tick lag" with the events moving from one queue to the next. :this_is_fine:
    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(6)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    const queue = await startQueue(server, undefined, {
        processEvent: (event) => runPlugins(server, event),
        processEventBatch: (events) => Promise.all(events.map((event) => runPlugins(server, event))),
        ingestEvent: () => Promise.resolve({ success: true }),
    })
    await advanceOneTick()

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).not.toBe(6)

    await queue.pause()

    const pluginQueue = await redis.llen(server.PLUGINS_CELERY_QUEUE)
    const defaultQueue = await redis.llen(server.CELERY_DEFAULT_QUEUE)

    expect(pluginQueue + defaultQueue).toBe(6)

    expect(pluginQueue).not.toBe(0)
    expect(defaultQueue).not.toBe(0)

    await delay(100)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(defaultQueue)

    await delay(100)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(defaultQueue)

    queue.resume()

    await delay(500)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(6)

    const oneTask = await redis.lpop(server.CELERY_DEFAULT_QUEUE)
    expect(JSON.parse(oneTask)['headers']['lang']).toBe('js')

    await queue.stop()
    await server.redisPool.release(redis)
    await stopServer()
})
