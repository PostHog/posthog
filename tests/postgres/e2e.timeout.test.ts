import { startPluginsServer } from '../../src/main/pluginsServer'
import { UUIDT } from '../../src/shared/utils'
import { LogLevel, PluginsServer } from '../../src/types'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

jest.setTimeout(60000) // 60 sec timeout

describe('e2e postgres ingestion timeout', () => {
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                event.properties = { passed: true }
                return event
            }
        `)
        const startResponse = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                TASK_TIMEOUT: 2,
                PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
                CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
                LOG_LEVEL: LogLevel.Log,
                KAFKA_ENABLED: false,
            },
            makePiscina
        )
        server = startResponse.server
        stopServer = startResponse.stop
        const redis = await server.redisPool.acquire()
        await redis.del(server.PLUGINS_CELERY_QUEUE)
        await redis.del(server.CELERY_DEFAULT_QUEUE)
        await server.redisPool.release(redis)

        posthog = createPosthog(server, pluginConfig39)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('event captured, processed, ingested', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        const uuid = new UUIDT().toString()
        posthog.capture('custom event', { name: 'haha', uuid, randomProperty: 'lololo' })
        await delayUntilEventIngested(() => server.db.fetchEvents())
        const events = await server.db.fetchEvents()
        expect(events.length).toBe(1)
        expect(events[0].properties.name).toEqual('haha')
        expect(events[0].properties.passed).not.toEqual(true)
    })
})
