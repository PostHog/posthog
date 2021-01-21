import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setError } from '../src/sql'
import { PluginConfig, PluginError, PluginsServer } from '../src/types'
import { createServer } from '../src/server'
import { resetTestDatabase } from './helpers/sql'

let server: PluginsServer
let closeServer: () => Promise<void>
beforeEach(async () => {
    ;[server, closeServer] = await createServer()
    await resetTestDatabase(`const processEvent = event => event`)
})
afterEach(() => {
    closeServer()
})

test('getPluginAttachmentRows', async () => {
    const rows1 = await getPluginAttachmentRows(server)
    expect(rows1).toEqual([
        {
            content_type: 'application/octet-stream',
            contents: Buffer.from([116, 101, 115, 116]),
            file_name: 'test.txt',
            file_size: 4,
            id: 1,
            key: 'maxmindMmdb',
            plugin_config_id: 39,
            team_id: 2,
        },
    ])
    server.db.query("update posthog_team set plugins_opt_in='f'")
    const rows2 = await getPluginAttachmentRows(server)
    expect(rows2).toEqual([])
})

test('getPluginConfigRows', async () => {
    await resetTestDatabase(`const processEvent = event => event`)
    const rows1 = await getPluginConfigRows(server)
    expect(rows1).toEqual([
        {
            config: {
                localhostIP: '94.224.212.175',
            },
            enabled: true,
            error: null,
            id: 39,
            order: 0,
            plugin_id: 60,
            team_id: 2,
        },
    ])
    server.db.query("update posthog_team set plugins_opt_in='f'")
    const rows2 = await getPluginConfigRows(server)
    expect(rows2).toEqual([])
})

test('getPluginRows', async () => {
    await resetTestDatabase(`const processEvent = event => event`)
    const rows1 = await getPluginRows(server)
    expect(rows1).toEqual([
        {
            archive: expect.any(Buffer),
            config_schema: {
                localhostIP: {
                    default: '',
                    hint: 'Useful if testing locally',
                    name: 'IP to use instead of 127.0.0.1',
                    order: 2,
                    required: false,
                    type: 'string',
                },
                maxmindMmdb: {
                    hint: 'The "GeoIP2 City" or "GeoLite2 City" database file',
                    markdown:
                        'Sign up for a [MaxMind.com](https://www.maxmind.com) account, download and extract the database and then upload the `.mmdb` file below',
                    name: 'GeoIP .mddb database',
                    order: 1,
                    required: true,
                    type: 'attachment',
                },
            },
            description: 'Ingest GeoIP data via MaxMind',
            error: null,
            from_json: false,
            from_web: false,
            id: 60,
            name: 'test-maxmind-plugin',
            plugin_type: 'custom',
            source: null,
            tag: '0.0.2',
            url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
        },
    ])
    server.db.query("update posthog_team set plugins_opt_in='f'")
    const rows2 = await getPluginRows(server)
    expect(rows2).toEqual([])
})

test('setError', async () => {
    const pluginConfig39: PluginConfig = {
        id: 39,
        team_id: 2,
        plugin_id: 60,
        enabled: true,
        order: 0,
        config: {},
        error: undefined,
    }
    server.db.query = jest.fn() as any

    await setError(server, null, pluginConfig39)
    expect(server.db.query).toHaveBeenCalledWith('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        null,
        pluginConfig39.id,
    ])

    const pluginError: PluginError = { message: 'error happened', time: 'now' }
    await setError(server, pluginError, pluginConfig39)
    expect(server.db.query).toHaveBeenCalledWith('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        pluginError,
        pluginConfig39.id,
    ])
})
