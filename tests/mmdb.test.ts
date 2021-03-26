import { ReaderModel } from '@maxmind/geoip2-node'
import { readFileSync } from 'fs'
import { DateTime } from 'luxon'
import * as fetch from 'node-fetch'
import { join } from 'path'

import { createServer } from '../src/shared/server'
import { resetTestDatabase } from './helpers/sql'

const mmdbBrotliContents = readFileSync(join(__dirname, 'assets', 'GeoLite2-City-Test.mmdb.br'))

async function resetTestDatabaseWithMmdb(): Promise<void> {
    await resetTestDatabase(undefined, undefined, {
        pluginAttachments: [
            {
                key: '@posthog/mmdb',
                content_type: 'vnd.maxmind.maxmind-db',
                file_name: `GeoLite2-City-${DateTime.local().toISODate()}.mmdb.br`,
                file_size: mmdbBrotliContents.byteLength,
                contents: mmdbBrotliContents,
                team_id: null,
                plugin_config_id: null,
            },
        ],
    })
}

//jest.mock('../src/shared/status')
jest.setTimeout(20_000)

afterEach(() => {
    jest.clearAllMocks()
})

test('fresh MMDB is downloaded if not cached and works', async () => {
    await resetTestDatabase()

    const [server, closeServer] = await createServer({ DISABLE_MMDB: false })

    expect(fetch).toHaveBeenCalledWith('https://mmdb.posthog.net/', { compress: false })
    expect(server.mmdb).toBeInstanceOf(ReaderModel)
    expect(server.DISABLE_MMDB).toBeFalsy()

    const cityResult = server.mmdb!.city('89.160.20.129')
    expect(cityResult.city).toBeDefined()
    expect(cityResult.city!.names.en).toStrictEqual('Linköping')

    await closeServer()
})

test('cached MMDB is used and works', async () => {
    await resetTestDatabaseWithMmdb()

    const [server, closeServer] = await createServer({ DISABLE_MMDB: false })

    expect(fetch).not.toHaveBeenCalled()
    expect(server.mmdb).toBeInstanceOf(ReaderModel)
    expect(server.DISABLE_MMDB).toBeFalsy()

    const cityResult = server.mmdb!.city('89.160.20.129')
    expect(cityResult.city).toBeDefined()
    expect(cityResult.city!.names.en).toStrictEqual('Linköping')

    await closeServer()
})
