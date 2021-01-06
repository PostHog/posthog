import { runPlugins, setupPlugins } from '../src/plugins'
import { createServer } from '../src/server'
import { LogLevel, PluginsServer } from '../src/types'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import {
    mockPluginTempFolder,
    mockPluginWithArchive,
    plugin60,
    pluginAttachment1,
    pluginConfig39,
} from './helpers/plugins'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setError } from './helpers/sqlMock'
jest.mock('../src/sql')

let mockServer: PluginsServer
let closeServer: () => Promise<void>
beforeEach(async () => {
    ;[mockServer, closeServer] = await createServer({ LOG_LEVEL: LogLevel.Log })
})
afterEach(() => {
    closeServer()
})

test('setupPlugins and runPlugins', async () => {
    getPluginRows.mockReturnValueOnce([plugin60])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])

    await setupPlugins(mockServer)
    const { plugins, pluginConfigs, pluginConfigsPerTeam, defaultConfigs } = mockServer

    expect(getPluginRows).toHaveBeenCalled()
    expect(getPluginAttachmentRows).toHaveBeenCalled()
    expect(getPluginConfigRows).toHaveBeenCalled()
    expect(setError).toHaveBeenCalled()

    expect(defaultConfigs).toEqual([]) // this will be used with global plugins
    expect(Array.from(plugins.entries())).toEqual([[60, plugin60]])
    expect(Array.from(pluginConfigs.keys())).toEqual([39])

    const pluginConfig = pluginConfigs.get(39)!
    expect(pluginConfig.id).toEqual(pluginConfig39.id)
    expect(pluginConfig.team_id).toEqual(pluginConfig39.team_id)
    expect(pluginConfig.plugin_id).toEqual(pluginConfig39.plugin_id)
    expect(pluginConfig.enabled).toEqual(pluginConfig39.enabled)
    expect(pluginConfig.order).toEqual(pluginConfig39.order)
    expect(pluginConfig.config).toEqual(pluginConfig39.config)
    expect(pluginConfig.error).toEqual(pluginConfig39.error)

    expect(pluginConfig.plugin).toEqual(plugin60)
    expect(pluginConfig.attachments).toEqual({
        maxmindMmdb: {
            content_type: pluginAttachment1.content_type,
            file_name: pluginAttachment1.file_name,
            contents: pluginAttachment1.contents,
        },
    })
    expect(pluginConfig.vm).toBeDefined()
    expect(Object.keys(pluginConfig.vm!.methods)).toEqual(['processEvent', 'processEventBatch'])

    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]).toEqual(null)
    expect(setError.mock.calls[0][2]).toEqual(pluginConfig)

    const processEvent = pluginConfig.vm!.methods['processEvent']
    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    await processEvent(event)

    expect(event.properties!['processed']).toEqual(true)

    event.properties!['processed'] = false

    const returnedEvent = await runPlugins(mockServer, event)
    expect(event.properties!['processed']).toEqual(true)
    expect(returnedEvent!.properties!['processed']).toEqual(true)
})

test('plugin returns null', async () => {
    getPluginRows.mockReturnValueOnce([mockPluginWithArchive('function processEvent (event, meta) { return null }')])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([])

    await setupPlugins(mockServer)

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runPlugins(mockServer, event)

    expect(returnedEvent).toEqual(null)
})

test('plugin meta has what it should have', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function setupPlugin (meta) { meta.global.key = 'value' } 
            function processEvent (event, meta) { event.properties=meta; return event }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runPlugins(mockServer, event)

    expect(Object.keys(returnedEvent!.properties!).sort()).toEqual([
        'attachments',
        'cache',
        'config',
        'global',
        'storage',
    ])
    expect(returnedEvent!.properties!['attachments']).toEqual({
        maxmindMmdb: { content_type: 'application/octet-stream', contents: Buffer.from('test'), file_name: 'test.txt' },
    })
    expect(returnedEvent!.properties!['config']).toEqual({ localhostIP: '94.224.212.175' })
    expect(returnedEvent!.properties!['global']).toEqual({ key: 'value' })
})

test('archive plugin with broken index.js does not do much', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function setupPlugin (met
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runPlugins(mockServer, { ...event })
    expect(returnedEvent).toEqual(event)

    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toEqual("Unexpected token ';'")
    expect(setError.mock.calls[0][1]!.name).toEqual('SyntaxError')
    expect(setError.mock.calls[0][1]!.stack).toContain('vm.js:')
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(setError.mock.calls[0][2]).toEqual(pluginConfigs.get(39))
    expect(pluginConfigs.get(39)!.vm).toEqual(null)
})

test('local plugin with broken index.js does not do much', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    const [plugin, unlink] = mockPluginTempFolder(`function setupPlugin (met`)
    getPluginRows.mockReturnValueOnce([plugin])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runPlugins(mockServer, { ...event })
    expect(returnedEvent).toEqual(event)

    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toEqual("Unexpected token ';'")
    expect(setError.mock.calls[0][1]!.name).toEqual('SyntaxError')
    expect(setError.mock.calls[0][1]!.stack).toContain('vm.js:')
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(setError.mock.calls[0][2]).toEqual(pluginConfigs.get(39))
    expect(pluginConfigs.get(39)!.vm).toEqual(null)

    unlink()
})

test('archive plugin with broken plugin.json does not do much', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(
            `function processEvent (event, meta) { event.properties.processed = true; return event }`,
            '{ broken: "plugin.json" -=- '
        ),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toEqual('Can not load plugin.json for plugin "test-maxmind-plugin"')
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(pluginConfigs.get(39)!.vm).toEqual(null)
})

test('local plugin with broken plugin.json does not do much', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    const [plugin, unlink] = mockPluginTempFolder(
        `function processEvent (event, meta) { event.properties.processed = true; return event }`,
        '{ broken: "plugin.json" -=- '
    )
    getPluginRows.mockReturnValueOnce([plugin])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toContain('Could not load posthog config at ')
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(pluginConfigs.get(39)!.vm).toEqual(null)

    unlink()
})

test('plugin with http urls must have an archive', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([{ ...plugin60, archive: null }])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toEqual(
        'Un-downloaded remote plugins not supported! Plugin: "test-maxmind-plugin"'
    )
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(pluginConfigs.get(39)!.vm).toEqual(null)
})

test("plugin with broken archive doesn't load", async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([{ ...plugin60, archive: Buffer.from('this is not a zip') }])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(mockServer)
    const { pluginConfigs } = mockServer

    expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
    expect(setError).toHaveBeenCalled()
    expect(setError.mock.calls[0][0]).toEqual(mockServer)
    expect(setError.mock.calls[0][1]!.message).toEqual('Could not read archive as .zip or .tgz')
    expect(setError.mock.calls[0][1]!.time).toBeDefined()
    expect(pluginConfigs.get(39)!.vm).toEqual(null)
})
