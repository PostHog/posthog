import * as IORedis from 'ioredis'

import { startPluginsServer } from '../../src/server'
import { LogLevel } from '../../src/types'
import { PluginsServer } from '../../src/types'
import { UUIDT } from '../../src/utils'
import { createPosthog, DummyPostHog } from '../../src/vm/extensions/posthog'
import { makePiscina } from '../../src/worker/piscina'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

jest.mock('../../src/status')
jest.setTimeout(60000) // 60 sec timeout

describe('e2e postgres ingestion', () => {
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        console.debug = jest.fn()

        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)
        const startResponse = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
                CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
                LOG_LEVEL: LogLevel.Log,
                KAFKA_ENABLED: false,
            },
            makePiscina
        )
        server = startResponse.server
        stopServer = startResponse.stop
        redis = await server.redisPool.acquire()

        await redis.del(server.PLUGINS_CELERY_QUEUE)
        await redis.del(server.CELERY_DEFAULT_QUEUE)

        posthog = createPosthog(server, pluginConfig39)
    })

    afterEach(async () => {
        await server.redisPool.release(redis)
        await stopServer()
    })

    test('event captured, processed, ingested', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        const uuid = new UUIDT().toString()
        posthog.capture('custom event', { name: 'haha', uuid, randomProperty: 'lololo' })
        await delayUntilEventIngested(() => server.db.fetchEvents())
        const events = await server.db.fetchEvents()
        expect(events.length).toBe(1)
        expect(events[0].properties.processed).toEqual('hell yes')
        expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())
    })
})
