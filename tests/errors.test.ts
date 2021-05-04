import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServer, PluginsServerConfig } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { pluginConfig39 } from './helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from './helpers/sql'
import { delayUntilEventIngested } from './shared/process-event'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue-errors',
    CELERY_DEFAULT_QUEUE: 'test-celery-default-queue-errors',
    LOG_LEVEL: LogLevel.Log,
    KAFKA_ENABLED: false,
}

describe('error do not take down ingestion', () => {
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            export async function processEvent (event, { jobs }) {
                if (event.properties.crash === 'throw') {
                    throw new Error('error thrown in plugin')
                } else if (event.properties.crash === 'throw in promise') {
                    void new Promise(() => { throw new Error('error thrown in plugin') }).then(() => {})
                } else if (event.properties.crash === 'reject in promise') {
                    void new Promise((_, rejects) => { rejects(new Error('error thrown in plugin')) }).then(() => {})
                }
                return event
            }
        `)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        server = startResponse.server
        stopServer = startResponse.stop
        posthog = createPosthog(server, pluginConfig39)

        const redis = await server.redisPool.acquire()
        await redis.del(server.PLUGINS_CELERY_QUEUE)
        await redis.del(server.CELERY_DEFAULT_QUEUE)
        await server.redisPool.release(redis)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('thrown errors', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            posthog.capture('broken event', { crash: 'throw' })
        }

        await delayUntilEventIngested(() => server.db.fetchEvents(), 4)

        expect((await server.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })

    test('unhandled promise errors', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            posthog.capture('broken event', { crash: 'throw in promise' })
        }

        await delayUntilEventIngested(() => server.db.fetchEvents(), 4)

        expect((await server.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })

    test('unhandled promise rejections', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            posthog.capture('broken event', { crash: 'reject in promise' })
        }

        await delayUntilEventIngested(() => server.db.fetchEvents(), 4)

        expect((await server.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })
})
