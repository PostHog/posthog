import { startQueue } from '../src/worker/queue'
import { createServer, defaultConfig } from '../src/server'
import { PluginsServer } from '../src/types'
import Client from '../src/celery/client'
import { runPlugins } from '../src/plugins'

function advanceOneTick() {
    return new Promise((resolve) => process.nextTick(resolve))
}

let mockServer: PluginsServer

beforeEach(async () => {
    // silence logs
    console.info = jest.fn()

    mockServer = (await createServer(defaultConfig))[0]
})

test('worker and task passing via redis', async () => {
    // Nothing in the redis queue
    const queue1 = await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(null)

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
    const client = new Client(mockServer.redis, mockServer.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    // It's there
    const queue2 = await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE)
    expect(queue2).toBeDefined()
    expect(queue2!.length).toBe(1)

    const item = JSON.parse(queue2![0])

    expect(item['content-type']).toBe('application/json')
    expect(item['headers']['lang']).toBe('js')
    expect(item['headers']['task']).toBe('posthog.tasks.process_event.process_event_with_plugins')
    expect(item['properties']['body_encoding']).toBe('base64')

    const body = Buffer.from(item['body'], 'base64').toString()
    const [args2, kwargs2] = JSON.parse(body)

    expect(args2).toEqual(args)
    expect(kwargs2).toEqual({})

    const queue = startQueue(mockServer, (event) => runPlugins(mockServer, event))
    await advanceOneTick()
    await advanceOneTick()

    // get the new processed task from CELERY_DEFAULT_QUEUE
    const queue3 = await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE)
    expect(queue3).toBeDefined()
    expect(queue3!.length).toBe(1)
    const processedItem = JSON.parse(queue3![0])

    expect(processedItem['content-type']).toBe('application/json')
    expect(processedItem['headers']['lang']).toBe('js')
    expect(processedItem['headers']['task']).toBe('posthog.tasks.process_event.process_event')
    expect(processedItem['properties']['body_encoding']).toBe('base64')

    const processedBody = Buffer.from(processedItem['body'], 'base64').toString()
    const [args3, kwargs3] = JSON.parse(processedBody)

    expect(args3).toEqual([])
    expect(kwargs3).toEqual(kwargs)

    const queue4 = await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE)
    const queue5 = await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE)
    await advanceOneTick()

    await queue.stop()
})

test('process multiple tasks', async () => {
    // Nothing in the redis queue
    const queue1 = await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE)
    expect(queue1).toBe(null)

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
    const client = new Client(mockServer.redis, mockServer.PLUGINS_CELERY_QUEUE)
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})
    client.sendTask('posthog.tasks.process_event.process_event_with_plugins', args, {})

    // There'll be a "tick lag" with the events moving from one queue to the next. :this_is_fine:
    expect((await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE))!.length).toBe(3)
    expect(await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE)).toBe(null)

    const queue = startQueue(mockServer, (event) => runPlugins(mockServer, event))
    await advanceOneTick()

    expect((await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE))!.length).toBe(2)
    expect(await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE)).toBe(null)

    await advanceOneTick()

    expect((await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE))!.length).toBe(1)
    expect((await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE))!.length).toBe(1)

    await advanceOneTick()

    expect((await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE))!.length).toBe(0)
    expect((await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE))!.length).toBe(2)

    await advanceOneTick()

    expect((await mockServer.redis.get(mockServer.PLUGINS_CELERY_QUEUE))!.length).toBe(0)
    expect((await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE))!.length).toBe(3)

    const defaultQueue = ((await mockServer.redis.get(mockServer.CELERY_DEFAULT_QUEUE)) as any) as string[]

    expect(defaultQueue.map((q) => JSON.parse(q)['headers']['lang']).join('-o-')).toBe('js-o-js-o-js')

    await queue.stop()
})
