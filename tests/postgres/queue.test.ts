import Client from '../../src/celery/client'
import { runPlugins } from '../../src/plugins/run'
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
        LOG_LEVEL: LogLevel.Log,
    })

    const redis = await server.redisPool.acquire()
    await redis.del(server.PLUGINS_CELERY_QUEUE)
    await redis.del(server.CELERY_DEFAULT_QUEUE)
    await server.redisPool.release(redis)
    return [server, stopServer]
}

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

    const queue = await startQueue(server, undefined, {
        processEvent: (event) => runPlugins(server, event),
        processEventBatch: (events) => Promise.all(events.map((event) => runPlugins(server, event))),
        ingestEvent: () => Promise.resolve({ success: true }),
    })
    await advanceOneTick()

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).not.toBe(6)

    await queue.pause()

    const pluginQueue = await redis.llen(server.PLUGINS_CELERY_QUEUE)

    expect(pluginQueue).toBeGreaterThan(0)

    await delay(100)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)

    await delay(100)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(pluginQueue)

    queue.resume()

    await delay(500)

    expect(await redis.llen(server.PLUGINS_CELERY_QUEUE)).toBe(0)

    await queue.stop()
    await server.redisPool.release(redis)
    await stopServer()
})
