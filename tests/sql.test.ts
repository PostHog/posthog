import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setError } from '../src/sql'
import { Plugin, PluginAttachmentDB, PluginConfig, PluginError, PluginsServer } from '../src/types'
import { createServer } from '../src/server'

let mockServer: PluginsServer
beforeEach(async () => {
    ;[mockServer] = await createServer()
})

test('getPluginAttachmentRows', async () => {
    const pluginAttachment1: PluginAttachmentDB = {
        id: 1,
        key: 'maxmindMmdb',
        content_type: 'application/octet-stream',
        file_name: 'test.txt',
        file_size: 4,
        contents: Buffer.from('test'),
        plugin_config_id: 39,
        team_id: 2,
    }
    mockServer.db.query = jest.fn((query, params) => ({
        rows: [pluginAttachment1],
    })) as any
    const rows = await getPluginAttachmentRows(mockServer)
    expect(rows).toEqual([pluginAttachment1])
    expect(mockServer.db.query).toHaveBeenCalledWith(
        "SELECT * FROM posthog_pluginattachment WHERE plugin_config_id in (SELECT id FROM posthog_pluginconfig WHERE enabled='t')"
    )
})

test('getPluginConfigRows', async () => {
    const pluginConfig39: PluginConfig = {
        id: 39,
        team_id: 2,
        plugin_id: 60,
        enabled: true,
        order: 0,
        config: {},
        error: undefined,
    }
    mockServer.db.query = jest.fn((query, params) => ({
        rows: [pluginConfig39],
    })) as any
    const rows = await getPluginConfigRows(mockServer)
    expect(rows).toEqual([pluginConfig39])
    expect(mockServer.db.query).toHaveBeenCalledWith("SELECT * FROM posthog_pluginconfig WHERE enabled='t'")
})

test('getPluginRows', async () => {
    const plugin60: Plugin = {
        id: 60,
        name: 'posthog-test-plugin',
        description: 'Ingest GeoIP data via MaxMind',
        url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
        config_schema: {},
        tag: '0.0.2',
        archive: null,
        error: undefined,
    }
    mockServer.db.query = jest.fn((query, params) => ({
        rows: [plugin60],
    })) as any
    const rows = await getPluginRows(mockServer)
    expect(rows).toEqual([plugin60])
    expect(mockServer.db.query).toHaveBeenCalledWith(
        "SELECT * FROM posthog_plugin WHERE id in (SELECT plugin_id FROM posthog_pluginconfig WHERE enabled='t' GROUP BY plugin_id)"
    )
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
    mockServer.db.query = jest.fn() as any

    await setError(mockServer, null, pluginConfig39)
    expect(mockServer.db.query).toHaveBeenCalledWith('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        null,
        pluginConfig39.id,
    ])

    const pluginError: PluginError = { message: 'error happened', time: 'now' }
    await setError(mockServer, pluginError, pluginConfig39)
    expect(mockServer.db.query).toHaveBeenCalledWith('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        pluginError,
        pluginConfig39.id,
    ])
})
