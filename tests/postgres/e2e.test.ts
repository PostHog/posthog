import * as IORedis from 'ioredis'

import { startPluginsServer } from '../../src/main/pluginsServer'
import { LogLevel } from '../../src/types'
import { PluginsServer } from '../../src/types'
import { delay, UUIDT } from '../../src/utils/utils'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { imports } from '../../src/worker/vm/imports'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

const { console: testConsole } = imports['test-utils/write-to-file']

jest.mock('../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

// TODO: merge these tests with clickhouse/e2e.test.ts
describe('e2e postgres ingestion', () => {
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        testConsole.reset()
        console.debug = jest.fn()

        await resetTestDatabase(`
            import { console as testConsole } from 'test-utils/write-to-file'
            export async function processEvent (event) {
                testConsole.log('processEvent')
                console.info('amogus')
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                event.properties['$snapshot_data'] = 'no way'
                return event
            }
            export function onEvent (event) {
                testConsole.log('onEvent', event.event)
            }
            export function onSnapshot (event) {
                testConsole.log('onSnapshot', event.event)
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

        posthog.capture('custom event', { name: 'haha', uuid })

        await delayUntilEventIngested(() => server.db.fetchEvents())

        const events = await server.db.fetchEvents()
        await delay(1000)

        expect(events.length).toBe(1)

        // processEvent ran and modified
        expect(events[0].properties.processed).toEqual('hell yes')
        expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

        // onEvent ran
        expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event']])
    })

    test('snapshot captured, processed, ingested', async () => {
        expect((await server.db.fetchSessionRecordingEvents()).length).toBe(0)

        const uuid = new UUIDT().toString()

        posthog.capture('$snapshot', { $session_id: '1234abc', $snapshot_data: 'yes way' })

        await delayUntilEventIngested(() => server.db.fetchSessionRecordingEvents())

        const events = await server.db.fetchSessionRecordingEvents()
        await delay(1000)

        expect(events.length).toBe(1)

        // processEvent did not modify
        expect(events[0].snapshot_data).toEqual('yes way')

        // onSnapshot ran
        expect(testConsole.read()).toEqual([['onSnapshot', '$snapshot']])
    })

    test('console logging is persistent', async () => {
        if (!server.ENABLE_PERSISTENT_CONSOLE) {
            // TODO: remove this return
            return
        }
        expect((await server.db.fetchEvents()).length).toBe(0)

        posthog.capture('custom event', { name: 'hehe', uuid: new UUIDT().toString() })

        await server.kafkaProducer?.flush()
        await delayUntilEventIngested(() => server.db.fetchPluginLogEntries())

        const pluginLogEntries = await server.db.fetchPluginLogEntries()

        expect(pluginLogEntries.length).toBe(1)
        expect(pluginLogEntries[0].type).toEqual('INFO')
        expect(pluginLogEntries[0].message).toEqual('amogus')
    })
})
