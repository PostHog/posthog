import { redisFactory } from './helpers/redis'
import { startQueue } from '../src/worker/queue'
import { createServer } from '../src/server'
import { LogLevel, PluginsServer } from '../src/types'
import Client from '../src/celery/client'
import { runPlugins } from '../src/plugins'

jest.mock('ioredis', () => redisFactory())

function advanceOneTick() {
    return new Promise((resolve) => process.nextTick(resolve))
}

async function getServer(): Promise<[PluginsServer, () => Promise<void>]> {
    const [server, stopServer] = await createServer({
        PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
        CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
        LOG_LEVEL: LogLevel.Log,
    })

    await server.redis.del(server.PLUGINS_CELERY_QUEUE)
    await server.redis.del(server.CELERY_DEFAULT_QUEUE)
    return [server, stopServer]
}

test('worker and task passing via redis', async () => {
    const [server, stopServer] = await getServer()
    // Nothing in the redis queue
    const queue1 = await server.redis.llen(server.PLUGINS_CELERY_QUEUE)
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
    const client = new Client(server.redis, server.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    // It's there
    const queue2 = await server.redis.llen(server.PLUGINS_CELERY_QUEUE)
    expect(queue2).toBe(1)

    const item2 = await server.redis.lpop(server.PLUGINS_CELERY_QUEUE)
    await server.redis.lpush(server.PLUGINS_CELERY_QUEUE, item2)
    const item = JSON.parse(item2)

    expect(item['content-type']).toBe('application/json')
    expect(item['headers']['lang']).toBe('js')
    expect(item['headers']['task']).toBe('posthog.tasks.process_event.process_event_with_plugins')
    expect(item['properties']['body_encoding']).toBe('base64')

    const body = Buffer.from(item['body'], 'base64').toString()
    const [args2, kwargs2] = JSON.parse(body)

    expect(args2).toEqual(args)
    expect(kwargs2).toEqual({})

    const queue = startQueue(
        server,
        (event) => runPlugins(server, event),
        (events) => Promise.all(events.map((event) => runPlugins(server, event)))
    )
    await advanceOneTick()
    await advanceOneTick()

    // get the new processed task from CELERY_DEFAULT_QUEUE
    const queue3 = await server.redis.llen(server.CELERY_DEFAULT_QUEUE)
    expect(queue3).toBe(1)
    const item3 = await server.redis.lpop(server.CELERY_DEFAULT_QUEUE)
    await server.redis.lpush(server.CELERY_DEFAULT_QUEUE, item3)
    const processedItem = JSON.parse(item3)

    expect(processedItem['content-type']).toBe('application/json')
    expect(processedItem['headers']['lang']).toBe('js')
    expect(processedItem['headers']['task']).toBe('posthog.tasks.process_event.process_event')
    expect(processedItem['properties']['body_encoding']).toBe('base64')

    const processedBody = Buffer.from(processedItem['body'], 'base64').toString()
    const [args3, kwargs3] = JSON.parse(processedBody)

    expect(args3).toEqual([])
    expect(kwargs3).toEqual(kwargs)

    const queue4 = await server.redis.llen(server.PLUGINS_CELERY_QUEUE)
    const queue5 = await server.redis.llen(server.CELERY_DEFAULT_QUEUE)
    await advanceOneTick()

    await queue.stop()
    await stopServer()
})

test('process multiple tasks', async () => {
    const [server, stopServer] = await getServer()
    // Nothing in the redis queue
    const queue1 = await server.redis.llen(server.PLUGINS_CELERY_QUEUE)
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
    const client = new Client(server.redis, server.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    // There'll be a "tick lag" with the events moving from one queue to the next. :this_is_fine:
    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    const queue = startQueue(
        server,
        (event) => runPlugins(server, event),
        (events) => Promise.all(events.map((event) => runPlugins(server, event)))
    )
    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(2)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(1)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(2)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    const defaultQueue = ((await server.redis.get(server.CELERY_DEFAULT_QUEUE)) as any) as string[]

    expect(defaultQueue.map((q) => JSON.parse(q)['headers']['lang']).join('-o-')).toBe('js-o-js-o-js')

    await queue.stop()
    await stopServer()
})

test('pause and resume queue', async () => {
    const [server, stopServer] = await getServer()
    // Nothing in the redis queue
    const queue1 = await server.redis.llen(server.PLUGINS_CELERY_QUEUE)
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
    const client = new Client(server.redis, server.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    // There'll be a "tick lag" with the events moving from one queue to the next. :this_is_fine:
    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(6)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    const queue = startQueue(
        server,
        (event) => runPlugins(server, event),
        (events) => Promise.all(events.map((event) => runPlugins(server, event)))
    )
    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(5)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(0)

    await queue.pause()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(5)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(5)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(5)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await queue.resume()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(5)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(4)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(1)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(2)

    await queue.pause()
    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    await queue.pause()
    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    await queue.resume()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(3)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(2)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(3)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(1)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(4)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(5)

    await advanceOneTick()

    expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)
    expect(await server.redis.llen(server.CELERY_DEFAULT_QUEUE)).toBe(6)

    const defaultQueue = ((await server.redis.get(server.CELERY_DEFAULT_QUEUE)) as any) as string[]

    expect(defaultQueue.map((q) => JSON.parse(q)['headers']['lang']).join('-o-')).toBe('js-o-js-o-js-o-js-o-js-o-js')

    await queue.stop()
    await stopServer()
})
