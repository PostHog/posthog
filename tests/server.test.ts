import * as Sentry from '@sentry/node'

import { startPluginsServer } from '../src/main/pluginsServer'
import { delay } from '../src/shared/utils'
import { LogLevel } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

jest.mock('@sentry/node')
jest.mock('../src/shared/sql')
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

test('plugin server staleness check', async () => {
    const testCode = `
        async function processEvent (event) {
            return event
        }
    `
    await resetTestDatabase(testCode)
    const pluginsServer = await startPluginsServer(
        {
            WORKER_CONCURRENCY: 2,
            STALENESS_RESTART_SECONDS: 5,
            LOG_LEVEL: LogLevel.Debug,
        },
        makePiscina
    )

    await delay(10000)

    expect(Sentry.captureMessage).toHaveBeenCalledWith(`Plugin Server has not ingested events for over 5 seconds!`, {
        extra: { instanceId: expect.any(String), lastActivity: expect.any(String), lastActivityType: 'serverStart' },
    })

    await pluginsServer.stop()
})
