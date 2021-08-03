import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { mocked } from 'ts-jest/utils'

import { Hub, LogLevel, PluginTaskType } from '../src/types'
import { clearError, processError } from '../src/utils/db/error'
import { createHub } from '../src/utils/db/hub'
import { delay, IllegalOperationError } from '../src/utils/utils'
import { loadPlugin } from '../src/worker/plugins/loadPlugin'
import { runProcessEvent } from '../src/worker/plugins/run'
import { loadSchedule, setupPlugins } from '../src/worker/plugins/setup'
import {
    commonOrganizationId,
    mockPluginSourceCode,
    mockPluginTempFolder,
    mockPluginWithArchive,
    plugin60,
    pluginAttachment1,
    pluginConfig39,
} from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows, setPluginCapabilities } from './helpers/sqlMock'

jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/status')
jest.mock('../src/utils/db/error')
jest.mock('../src/worker/plugins/loadPlugin', () => {
    const { loadPlugin } = jest.requireActual('../src/worker/plugins/loadPlugin')
    return { loadPlugin: jest.fn().mockImplementation(loadPlugin) }
})

let hub: Hub
let closeHub: () => Promise<void>

beforeEach(async () => {
    ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
    console.warn = jest.fn() as any
    await resetTestDatabase()
})

afterEach(async () => {
    await closeHub()
})

test('setupPlugins and runProcessEvent', async () => {
    getPluginRows.mockReturnValueOnce([{ ...plugin60 }])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])

    await setupPlugins(hub)
    const { plugins, pluginConfigs } = hub

    expect(getPluginRows).toHaveBeenCalled()
    expect(getPluginAttachmentRows).toHaveBeenCalled()
    expect(getPluginConfigRows).toHaveBeenCalled()

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
    const vm = await pluginConfig.vm!.resolveInternalVm
    expect(Object.keys(vm!.methods).sort()).toEqual([
        'exportEvents',
        'onEvent',
        'onSnapshot',
        'processEvent',
        'setupPlugin',
        'teardownPlugin',
    ])

    // async loading of capabilities
    expect(setPluginCapabilities).toHaveBeenCalled()
    expect(Array.from(plugins.entries())).toEqual([
        [
            60,
            {
                ...plugin60,
                capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
            },
        ],
    ])

    expect(clearError).toHaveBeenCalledWith(hub, pluginConfig)

    const processEvent = vm!.methods['processEvent']!
    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    await processEvent(event)

    expect(event.properties!['processed']).toEqual(true)

    event.properties!['processed'] = false

    const returnedEvent = await runProcessEvent(hub, event)
    expect(event.properties!['processed']).toEqual(true)
    expect(returnedEvent!.properties!['processed']).toEqual(true)
})

test('plugin returns null', async () => {
    getPluginRows.mockReturnValueOnce([mockPluginWithArchive('function processEvent (event, meta) { return null }')])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([])

    await setupPlugins(hub)

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, event)

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

    await setupPlugins(hub)

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, event)

    expect(Object.keys(returnedEvent!.properties!).sort()).toEqual([
        '$plugins_deferred',
        '$plugins_failed',
        '$plugins_succeeded',
        'attachments',
        'cache',
        'config',
        'geoip',
        'global',
        'jobs',
        'metrics',
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

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!
    pluginConfig.vm!.totalInitAttemptsCounter = 20 // prevent more retries
    await delay(4000) // processError is called at end of retries
    expect(await pluginConfig.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, { ...event })
    expect(returnedEvent).toEqual(event)

    expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
    const error = mocked(processError).mock.calls[0][2]! as Error
    expect(error.message).toContain(': Unexpected token, expected ","')
})

test('local plugin with broken index.js does not do much', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    const [plugin, unlink] = mockPluginTempFolder(`function setupPlugin (met`)
    getPluginRows.mockReturnValueOnce([plugin])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!
    pluginConfig.vm!.totalInitAttemptsCounter = 20 // prevent more retries
    await delay(4000) // processError is called at end of retries
    expect(await pluginConfig.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, { ...event })
    expect(returnedEvent).toEqual(event)

    expect(processError).toHaveBeenCalledWith(hub, pluginConfig, expect.any(SyntaxError))
    const error = mocked(processError).mock.calls[0][2]! as Error
    expect(error.message).toContain(': Unexpected token, expected ","')

    unlink()
})

test('plugin changing event.team_id throws error', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function processEvent (event, meta) {
                event.team_id = 400
                return event
            }
        `),
    ])

    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, event)

    const expectedReturnedEvent = {
        event: '$test',
        properties: {
            $plugins_failed: ['test-maxmind-plugin (39)'],
            $plugins_succeeded: [],
            $plugins_deferred: [],
        },
        team_id: 2,
    }
    expect(returnedEvent).toEqual(expectedReturnedEvent)

    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfigs.get(39)!,
        new IllegalOperationError('Plugin tried to change event.team_id'),
        expectedReturnedEvent
    )
})

test('plugin throwing error does not prevent ingestion and failure is noted in event', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function processEvent (event) {
                throw new Error('I always fail!')
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, { ...event })

    const expectedReturnEvent = {
        ...event,
        properties: {
            $plugins_failed: ['test-maxmind-plugin (39)'],
            $plugins_succeeded: [],
            $plugins_deferred: [],
        },
    }
    expect(returnedEvent).toEqual(expectedReturnEvent)
})

test('events have property $plugins_succeeded set to the plugins that succeeded', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function processEvent (event) {
                return event
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, { ...event })

    const expectedReturnEvent = {
        ...event,
        properties: {
            $plugins_failed: [],
            $plugins_succeeded: ['test-maxmind-plugin (39)'],
            $plugins_deferred: [],
        },
    }
    expect(returnedEvent).toEqual(expectedReturnEvent)
})

test('events have property $plugins_deferred set to the plugins that run after processEvent', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function onEvent (event) {
                return event
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent
    const returnedEvent = await runProcessEvent(hub, { ...event })

    const expectedReturnEvent = {
        ...event,
        properties: {
            $plugins_failed: [],
            $plugins_succeeded: [],
            $plugins_deferred: ['test-maxmind-plugin (39)'],
        },
    }
    expect(returnedEvent).toEqual(expectedReturnEvent)
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

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfigs.get(39)!,
        `Can not load plugin.json for plugin test-maxmind-plugin ID ${plugin60.id} (organization ID ${commonOrganizationId})`
    )

    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})
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

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfigs.get(39)!,
        expect.stringContaining('Could not load posthog config at ')
    )
    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})

    unlink()
})

test('plugin with http urls must have an archive', async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([{ ...plugin60, archive: null, is_global: true }])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfigs.get(39)!,
        `Tried using undownloaded remote plugin test-maxmind-plugin ID ${plugin60.id} (organization ID ${commonOrganizationId} - global), which is not supported!`
    )
    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})
})

test("plugin with broken archive doesn't load", async () => {
    // silence some spam
    console.log = jest.fn()
    console.error = jest.fn()

    getPluginRows.mockReturnValueOnce([{ ...plugin60, archive: Buffer.from('this is not a zip') }])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    expect(pluginConfigs.get(39)!.plugin!.url).toContain('https://')
    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfigs.get(39)!,
        Error('Could not read archive as .zip or .tgz')
    )
    expect(await pluginConfigs.get(39)!.vm!.getTasks(PluginTaskType.Schedule)).toEqual({})
})

test('plugin config order', async () => {
    const setOrderCode = (id: number) => {
        return `
            function processEvent(event) {
                if (!event.properties.plugins) { event.properties.plugins = [] }
                event.properties.plugins.push(${id})
                return event
            }
        `
    }

    getPluginRows.mockReturnValueOnce([
        { ...plugin60, id: 60, plugin_type: 'source', archive: null, source: setOrderCode(60) },
        { ...plugin60, id: 61, plugin_type: 'source', archive: null, source: setOrderCode(61) },
        { ...plugin60, id: 62, plugin_type: 'source', archive: null, source: setOrderCode(62) },
    ])
    getPluginAttachmentRows.mockReturnValueOnce([])
    getPluginConfigRows.mockReturnValueOnce([
        { ...pluginConfig39, order: 2 },
        { ...pluginConfig39, plugin_id: 61, id: 40, order: 1 },
        { ...pluginConfig39, plugin_id: 62, id: 41, order: 3 },
    ])

    await setupPlugins(hub)
    const { pluginConfigsPerTeam } = hub

    expect(pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
        [40, 1],
        [39, 2],
        [41, 3],
    ])

    const event = { event: '$test', properties: {}, team_id: 2 } as PluginEvent

    const returnedEvent1 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
    expect(returnedEvent1!.properties!.plugins).toEqual([61, 60, 62])

    const returnedEvent2 = await runProcessEvent(hub, { ...event, properties: { ...event.properties } })
    expect(returnedEvent2!.properties!.plugins).toEqual([61, 60, 62])
})

test('plugin with archive loads capabilities', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!

    await pluginConfig.vm?.resolveInternalVm
    // async loading of capabilities

    expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['processEvent', 'setupPlugin'])
    expect(pluginConfig.plugin!.capabilities!.jobs).toHaveLength(0)
    expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toHaveLength(0)
})

test('plugin with archive loads all capabilities, no random caps', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export function processEvent (event, meta) { event.properties={"x": 1}; return event }
            export function randomFunction (event, meta) { return event}
            export function onEvent (event, meta) { return event }

            export function runEveryHour(meta) {console.log('1')}

            export const jobs = {
                x: (event, meta) => console.log(event)
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!

    await pluginConfig.vm?.resolveInternalVm
    // async loading of capabilities

    expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
    expect(pluginConfig.plugin!.capabilities!.jobs).toEqual(['x'])
    expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual(['runEveryHour'])
})

test('plugin with source file loads capabilities', async () => {
    const [plugin, unlink] = mockPluginTempFolder(`
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onEvent (event, meta) { return event }
    `)

    getPluginRows.mockReturnValueOnce([plugin])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!

    await pluginConfig.vm?.resolveInternalVm
    // async loading of capabilities

    expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onEvent', 'processEvent'])
    expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
    expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])

    unlink()
})

test('plugin with source code loads capabilities', async () => {
    const source_code = `
        function processEvent (event, meta) { event.properties={"x": 1}; return event }
        function randomFunction (event, meta) { return event}
        function onSnapshot (event, meta) { return event }
    `
    getPluginRows.mockReturnValueOnce([mockPluginSourceCode(source_code)])

    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const { pluginConfigs } = hub

    const pluginConfig = pluginConfigs.get(39)!

    await pluginConfig.vm?.resolveInternalVm
    // async loading of capabilities

    expect(pluginConfig.plugin!.capabilities!.methods!.sort()).toEqual(['onSnapshot', 'processEvent'])
    expect(pluginConfig.plugin!.capabilities!.jobs).toEqual([])
    expect(pluginConfig.plugin!.capabilities!.scheduled_tasks).toEqual([])
})

test('reloading plugins after config changes', async () => {
    const makePlugin = (id: number, updated_at = '2020-11-02'): any => ({
        ...plugin60,
        id,
        plugin_type: 'source',
        archive: null,
        source: setOrderCode(60),
        updated_at,
    })
    const makeConfig = (plugin_id: number, id: number, order: number, updated_at = '2020-11-02'): any => ({
        ...pluginConfig39,
        plugin_id,
        id,
        order,
        updated_at,
    })

    const setOrderCode = (id: number) => {
        return `
            function processEvent(event) {
                if (!event.properties.plugins) { event.properties.plugins = [] }
                event.properties.plugins.push(${id})
                return event
            }
        `
    }

    getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(62), makePlugin(63)])
    getPluginAttachmentRows.mockReturnValue([])
    getPluginConfigRows.mockReturnValue([
        makeConfig(60, 39, 0),
        makeConfig(61, 41, 1),
        makeConfig(62, 40, 3),
        makeConfig(63, 42, 2),
    ])

    await setupPlugins(hub)
    await loadSchedule(hub)

    expect(loadPlugin).toHaveBeenCalledTimes(4)
    expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 62, 63]))
    expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 40, 41, 42]))

    expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
        [39, 0],
        [41, 1],
        [42, 2],
        [40, 3],
    ])

    getPluginRows.mockReturnValue([makePlugin(60), makePlugin(61), makePlugin(63, '2021-02-02'), makePlugin(64)])
    getPluginAttachmentRows.mockReturnValue([])
    getPluginConfigRows.mockReturnValue([
        makeConfig(60, 39, 0),
        makeConfig(61, 41, 3, '2021-02-02'),
        makeConfig(63, 42, 2),
        makeConfig(64, 43, 1),
    ])

    await setupPlugins(hub)
    await loadSchedule(hub)

    expect(loadPlugin).toHaveBeenCalledTimes(4 + 3)
    expect(Array.from(hub.plugins.keys())).toEqual(expect.arrayContaining([60, 61, 63, 64]))
    expect(Array.from(hub.pluginConfigs.keys())).toEqual(expect.arrayContaining([39, 41, 42, 43]))

    expect(hub.pluginConfigsPerTeam.get(pluginConfig39.team_id)?.map((c) => [c.id, c.order])).toEqual([
        [39, 0],
        [43, 1],
        [42, 2],
        [41, 3],
    ])
})

test("capabilities don't reload without changes", async () => {
    getPluginRows.mockReturnValueOnce([{ ...plugin60 }]).mockReturnValueOnce([
        {
            ...plugin60,
            capabilities: { jobs: [], scheduled_tasks: [], methods: ['processEvent'] },
        },
    ]) // updated in DB via first `setPluginCapabilities` call.
    getPluginAttachmentRows.mockReturnValue([pluginAttachment1])
    getPluginConfigRows.mockReturnValue([pluginConfig39])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!

    await pluginConfig.vm?.resolveInternalVm
    // async loading of capabilities
    expect(setPluginCapabilities.mock.calls.length).toBe(1)

    pluginConfig.updated_at = new Date().toISOString()
    // config is changed, but capabilities haven't changed

    await setupPlugins(hub)
    const newPluginConfig = hub.pluginConfigs.get(39)!

    await newPluginConfig.vm?.resolveInternalVm
    // async loading of capabilities

    expect(newPluginConfig.plugin).not.toBe(pluginConfig.plugin)
    expect(setPluginCapabilities.mock.calls.length).toBe(1)
    expect(newPluginConfig.plugin!.capabilities).toEqual(pluginConfig.plugin!.capabilities)
})

test('plugin lazy loads capabilities', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function onEvent (event, meta) { event.properties={"x": 1}; return event }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!
    expect(pluginConfig.plugin!.capabilities).toEqual({})
})

test('plugin sets exported metrics', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export const metrics = {
                'metric1': 'sum',
                'metric2': 'mAx',
                'metric3': 'MIN'
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!

    expect(pluginConfig.plugin!.metrics).toEqual({
        metric1: 'sum',
        metric2: 'max',
        metric3: 'min',
    })
})

test('exportEvents automatically sets metrics', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export function exportEvents() {}
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!

    expect(pluginConfig.plugin!.metrics).toEqual({
        events_delivered_successfully: 'sum',
        events_seen: 'sum',
        other_errors: 'sum',
        retry_errors: 'sum',
        undelivered_events: 'sum',
    })
})

test('plugin vm is not setup if metric type is unsupported', async () => {
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export const metrics = {
                'unsupportedMetric': 'avg',
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!
    const vm = await pluginConfig.vm?.resolveInternalVm

    expect(vm).toEqual(null)
    expect(pluginConfig.plugin!.metrics).toEqual({})
})

test('metrics API works as expected', async () => {
    const testEvent = { event: '$test', properties: {}, team_id: 2, distinct_id: 'some id' } as PluginEvent
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export const metrics = {
                'metric1': 'sum',
                'metric2': 'max',
                'metric3': 'min'
            }

            export function processEvent(event, { metrics }) {
                metrics['metric1'].increment(100)
                metrics['metric1'].increment(10)
                metrics['metric1'].increment(-10)
                metrics['metric2'].max(5)
                metrics['metric2'].max(10)
                metrics['metric3'].min(4)
                metrics['metric3'].min(1)
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!
    await pluginConfig.vm?.resolveInternalVm
    await runProcessEvent(hub, testEvent)

    expect(hub.pluginMetricsManager.metricsPerPluginConfig[39].metrics).toEqual({
        metric1: 100,
        metric2: 10,
        metric3: 1,
    })
})

test('metrics method will fail for wrongly specified metric type', async () => {
    const testEvent = { event: '$test', properties: {}, team_id: 2, distinct_id: 'some id' } as PluginEvent
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export const metrics = {
                'i_should_increment': 'sum'
            }

            export function processEvent(event, { metrics }) {
                metrics['i_should_increment'].max(100)
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!
    await pluginConfig.vm?.resolveInternalVm
    await runProcessEvent(hub, testEvent)

    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfig,
        new TypeError('metrics.i_should_increment.max is not a function'),
        expect.anything()
    )
})

test('metrics methods only support numbers', async () => {
    const testEvent = { event: '$test', properties: {}, team_id: 2, distinct_id: 'some id' } as PluginEvent
    getPluginRows.mockReturnValueOnce([
        mockPluginWithArchive(`
            export const metrics = {
                'metric1': 'sum'
            }

            export function processEvent(event, { metrics }) {
                metrics['metric1'].increment('im not a number, but im also not NaN')
            }
        `),
    ])
    getPluginConfigRows.mockReturnValueOnce([pluginConfig39])
    getPluginAttachmentRows.mockReturnValueOnce([pluginAttachment1])

    await setupPlugins(hub)
    const pluginConfig = hub.pluginConfigs.get(39)!
    await pluginConfig.vm?.resolveInternalVm
    await runProcessEvent(hub, testEvent)

    expect(processError).toHaveBeenCalledWith(
        hub,
        pluginConfig,
        new IllegalOperationError('Only numbers are allowed for operations on metrics'),
        expect.anything()
    )
})

describe('loadSchedule()', () => {
    const mockConfig = (tasks: any) => ({ vm: { getTasks: () => Promise.resolve(tasks) } })

    const hub = {
        pluginConfigs: new Map(
            Object.entries({
                1: {},
                2: mockConfig({ runEveryMinute: null, runEveryHour: () => 123 }),
                3: mockConfig({ runEveryMinute: () => 123, foo: () => 'bar' }),
            })
        ),
    } as any

    it('sets server.pluginSchedule once all plugins are ready', async () => {
        const promise = loadSchedule(hub)
        expect(hub.pluginSchedule).toEqual(null)

        await promise

        expect(hub.pluginSchedule).toEqual({
            runEveryMinute: ['3'],
            runEveryHour: ['2'],
            runEveryDay: [],
        })
    })
})
