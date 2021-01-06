import { startPluginsServer } from '../src/server'
import { LogLevel } from '../src/types'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/sql')
jest.setTimeout(60000) // 60 sec timeout

test('startPluginsServer', async () => {
    const testCode = `
        async function processEvent (event) {
            return event
        }
    `
    await resetTestDatabase(testCode)
    const pluginsServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Debug,
        },
        makePiscina
    )

    await pluginsServer.stop()
})
