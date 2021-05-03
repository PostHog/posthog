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
            async function processEvent (event, meta) {
                if (event.properties.crash === 'await') {
                    await meta.retry('test', {}, -100)
                } else if (event.properties.crash === 'void') {
                    void meta.retry('test', {}, -100)
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

    test('awaited errors', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            posthog.capture('broken event', { crash: 'await' })
        }

        await delayUntilEventIngested(() => server.db.fetchEvents(), 4)

        expect((await server.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('Retries must happen between 1 seconds and 24 hours from now')
    })

    test('unhandled promise rejections', async () => {
        expect((await server.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            posthog.capture('broken event', { crash: 'void' })
        }

        await delayUntilEventIngested(() => server.db.fetchEvents(), 4)

        expect((await server.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('Retries must happen between 1 seconds and 24 hours from now')
    })
})
