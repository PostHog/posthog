import { LOCKED_RESOURCE } from '../src/main/job-queues/job-queue-consumer'
import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel } from '../src/types'
import { createServer } from '../src/utils/db/server'
import { delay } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog } from '../src/worker/vm/extensions/posthog'
import { imports } from '../src/worker/vm/imports'
import { resetGraphileSchema } from './helpers/graphile'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/db/sql')
jest.setTimeout(60000) // 60 sec timeout

const { console: testConsole } = imports['test-utils/write-to-file']

describe('job queues', () => {
    beforeEach(async () => {
        testConsole.reset()

        const [server, stopServer] = await createServer()
        const redis = await server.redisPool.acquire()
        await redis.del(LOCKED_RESOURCE)
        await server.redisPool.release(redis)
        await stopServer()
    })

    describe('fs queue', () => {
        test('onRetry gets called', async () => {
            const testCode = `
                import { console } from 'test-utils/write-to-file'

                export async function onRetry (type, payload, meta) {
                    console.log('retrying event!', type)
                }
                export async function processEvent (event, meta) {
                    if (event.properties?.hi === 'ha') {
                        console.log('processEvent')
                        meta.retry('processEvent', event, 1)
                    }
                    return event
                }
            `
            await resetTestDatabase(testCode)
            const server = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 2,
                    LOG_LEVEL: LogLevel.Debug,
                    RETRY_QUEUES: 'fs',
                },
                makePiscina
            )
            const posthog = createPosthog(server.server, pluginConfig39)

            posthog.capture('my event', { hi: 'ha' })
            await delay(10000)

            expect(testConsole.read()).toEqual([['processEvent'], ['retrying event!', 'processEvent']])

            await server.stop()
        })
    })

    describe('graphile', () => {
        beforeEach(async () => {
            await resetGraphileSchema()
        })

        test('graphile retry queue', async () => {
            const testCode = `
                import { console } from 'test-utils/write-to-file'

                export async function onRetry (type, payload, meta) {
                    console.log('retrying event!', type)
                }
                export async function processEvent (event, meta) {
                    if (event.properties?.hi === 'ha') {
                        console.log('processEvent')
                        meta.retry('processEvent', event, 1)
                    }
                    return event
                }
            `
            await resetTestDatabase(testCode)
            const server = await startPluginsServer(
                {
                    WORKER_CONCURRENCY: 2,
                    LOG_LEVEL: LogLevel.Debug,
                    RETRY_QUEUES: 'graphile',
                },
                makePiscina
            )
            const posthog = createPosthog(server.server, pluginConfig39)

            posthog.capture('my event', { hi: 'ha' })
            await delay(5000)

            expect(testConsole.read()).toEqual([['processEvent'], ['retrying event!', 'processEvent']])

            await server.stop()
        })
    })
})
