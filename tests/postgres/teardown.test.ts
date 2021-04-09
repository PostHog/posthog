import { startPluginsServer } from '../../src/main/pluginsServer'
import { LogLevel } from '../../src/types'
import { makePiscina } from '../../src/worker/piscina'
import { pluginConfig39 } from '../helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/shared/status')
jest.setTimeout(60000) // 60 sec timeout

describe('teardown', () => {
    test('teardown code runs', async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
            async function teardownPlugin() {
                throw new Error('This Happened In The Teardown Palace')
            }
        `)
        const { stop } = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
                CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
                LOG_LEVEL: LogLevel.Log,
                KAFKA_ENABLED: false,
            },
            makePiscina
        )

        const error1 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error1).toBe(null)

        await stop()

        // verify the teardownPlugin code runs
        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('This Happened In The Teardown Palace')
    })
})
