import { Hub, PluginConfig, PluginError } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import {
    disablePlugin,
    getPluginAttachmentRows,
    getPluginConfigRows,
    getPluginRows,
    setError,
    setPluginMetrics,
} from '../src/utils/db/sql'
import { commonOrganizationId } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

let hub: Hub
let closeHub: () => Promise<void>

beforeEach(async () => {
    ;[hub, closeHub] = await createHub()
    await resetTestDatabase(`const processEvent = event => event`)
})

afterEach(async () => {
    await closeHub()
})

test('getPluginAttachmentRows', async () => {
    const rowsExpected = [
        {
            content_type: 'application/octet-stream',
            contents: Buffer.from([116, 101, 115, 116]),
            file_name: 'test.txt',
            file_size: 4,
            id: 42666,
            key: 'maxmindMmdb',
            plugin_config_id: 39,
            team_id: 2,
        },
    ]

    const rows1 = await getPluginAttachmentRows(hub)
    expect(rows1).toEqual(rowsExpected)
    await hub.db.postgresQuery("update posthog_team set plugins_opt_in='f'", undefined, 'testTag')
    const rows2 = await getPluginAttachmentRows(hub)
    expect(rows2).toEqual(rowsExpected)
})

test('getPluginConfigRows', async () => {
    const rowsExpected = [
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
            created_at: expect.anything(),
            updated_at: expect.anything(),
        },
    ]

    const rows1 = await getPluginConfigRows(hub)
    expect(rows1).toEqual(rowsExpected)
    await hub.db.postgresQuery("update posthog_team set plugins_opt_in='f'", undefined, 'testTag')
    const rows2 = await getPluginConfigRows(hub)
    expect(rows2).toEqual(rowsExpected)
})

test('getPluginRows', async () => {
    const rowsExpected = [
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
            is_global: false,
            is_preinstalled: false,
            organization_id: commonOrganizationId,
            latest_tag: null,
            latest_tag_checked_at: null,
            name: 'test-maxmind-plugin',
            plugin_type: 'custom',
            source: null,
            tag: '0.0.2',
            url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
            created_at: expect.anything(),
            updated_at: expect.anything(),
            capabilities: {},
            metrics: {},
        },
    ]

    const rows1 = await getPluginRows(hub)
    expect(rows1).toEqual(rowsExpected)
    await hub.db.postgresQuery("update posthog_team set plugins_opt_in='f'", undefined, 'testTag')
    const rows2 = await getPluginRows(hub)
    expect(rows2).toEqual(rowsExpected)
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
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    }
    hub.db.postgresQuery = jest.fn() as any

    await setError(hub, null, pluginConfig39)
    expect(hub.db.postgresQuery).toHaveBeenCalledWith(
        'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
        [null, pluginConfig39.id],
        'updatePluginConfigError'
    )

    const pluginError: PluginError = { message: 'error happened', time: 'now' }
    await setError(hub, pluginError, pluginConfig39)
    expect(hub.db.postgresQuery).toHaveBeenCalledWith(
        'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
        [pluginError, pluginConfig39.id],
        'updatePluginConfigError'
    )
})

describe('disablePlugin', () => {
    test('disablePlugin query builds correctly', async () => {
        hub.db.postgresQuery = jest.fn() as any

        await disablePlugin(hub, 39)
        expect(hub.db.postgresQuery).toHaveBeenCalledWith(
            `UPDATE posthog_pluginconfig SET enabled='f' WHERE id=$1 AND enabled='t'`,
            [39],
            'disablePlugin'
        )
    })

    test('disablePlugin disables a plugin', async () => {
        const rowsBefore = await getPluginConfigRows(hub)
        expect(rowsBefore[0].plugin_id).toEqual(60)
        expect(rowsBefore[0].enabled).toEqual(true)

        await disablePlugin(hub, 39)

        const rowsAfter = await getPluginConfigRows(hub)
        expect(rowsAfter).toEqual([])
    })
})

describe('setPluginMetrics', () => {
    test('setPluginMetrics sets metrics correctly', async () => {
        const pluginConfig39: PluginConfig = {
            id: 39,
            team_id: 2,
            plugin_id: 60,
            enabled: true,
            order: 0,
            config: {},
            error: undefined,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        }

        const rowsBefore = await getPluginRows(hub)
        expect(rowsBefore[0].id).toEqual(60)
        expect(rowsBefore[0].metrics).toEqual({})

        await setPluginMetrics(hub, pluginConfig39, { metric1: 'sum' })

        const rowsAfter = await getPluginRows(hub)
        expect(rowsAfter[0].metrics).toEqual({ metric1: 'sum' })
    })
})
