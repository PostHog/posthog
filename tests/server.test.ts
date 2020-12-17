import { startPluginsServer } from '../src/server'
import { LogLevel } from '../src/types'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { makePiscina } from '../src/worker/piscina'
import { mockJestWithIndex } from './helpers/plugins'

jest.mock('../src/sql')
jest.setTimeout(60000) // 60 sec timeout

function createEvent(index = 0): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
    }
}

test('startPluginsServer', async () => {
    const testCode = `
        async function processEvent (event) {
            return event
        }
    `
    const pluginsServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 2,
            LOG_LEVEL: LogLevel.Debug,
            __jestMock: mockJestWithIndex(testCode),
        },
        makePiscina
    )

    await pluginsServer.stop()
})
