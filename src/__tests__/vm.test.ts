import { createPluginConfigVM } from '../vm'
import { PluginConfig, PluginsServer, Plugin } from '../types'
import { PluginEvent } from 'posthog-plugins'
import { defaultConfig } from '../server'
import Redis from 'ioredis'
import fetch from 'node-fetch'
import { Pool } from 'pg'

const defaultEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 3,
    now: new Date().toISOString(),
    event: 'default event',
}

let mockServer: PluginsServer

const mockPlugin: Plugin = {
    id: 4,
    name: 'mock-plugin',
    description: 'Mock Plugin in Tests',
    url: 'http://plugins.posthog.com/mock-plugin',
    config_schema: {},
    tag: 'v1.0.0',
    archive: null,
    error: undefined,
}

const mockConfig: PluginConfig = {
    id: 4,
    team_id: 2,
    plugin: mockPlugin,
    plugin_id: mockPlugin.id,
    enabled: true,
    order: 0,
    config: { configKey: 'configValue' },
    error: undefined,
    attachments: {},
    vm: null,
}

beforeEach(() => {
    mockServer = {
        ...defaultConfig,
        db: new Pool(),
        redis: new Redis('redis://mockmockmock/'),
    }
})

afterEach(async () => {
    mockServer.redis.disconnect()
    await mockServer.db.end()
    jest.clearAllMocks()
})

test('empty plugins', async () => {
    const indexJs = ''
    const libJs = ''
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs, libJs)

    expect(Object.keys(vm).sort()).toEqual(['methods', 'vm'])
    expect(Object.keys(vm.methods).sort()).toEqual(['processEvent'])
    expect(vm.methods.processEvent).toEqual(undefined)
})

test('processEvent', async () => {
    const indexJs = `
        function processEvent (event, meta) {
            event.event = 'changed event'
            return event
        }  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    expect(vm.methods.processEvent).not.toEqual(undefined)

    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }

    const newEvent = await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
    expect(newEvent.event).toEqual('changed event')
    expect(newEvent).toBe(event)
})

test('processEvent without returning', async () => {
    const indexJs = `
        function processEvent (event, meta) {
            event.event = 'changed event'
        }  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    expect(vm.methods.processEvent).not.toEqual(undefined)

    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }

    const newEvent = await vm.methods.processEvent(event)
    // this will be changed
    expect(event.event).toEqual('changed event')
    // but nothing was returned --> bail
    expect(newEvent).toEqual(undefined)
})

test('async processEvent', async () => {
    const indexJs = `
        async function processEvent (event, meta) {
            await new Promise((resolve) => resolve())
            event.event = 'changed event'
            await new Promise((resolve) => resolve())
            return event
        }  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)

    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
})

test('module.exports override', async () => {
    const indexJs = `
        function myProcessEventFunction (event, meta) {
            event.event = 'changed event';
            return event
        }
        module.exports = { processEvent: myProcessEventFunction }  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)

    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
})

test('module.exports set', async () => {
    const indexJs = `
        function myProcessEventFunction (event, meta) {
            event.event = 'changed event';
            return event
        }
        module.exports.processEvent = myProcessEventFunction  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)

    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
})

test('exports override', async () => {
    const indexJs = `
        function myProcessEventFunction (event, meta) {
            event.event = 'changed event';
            return event
        }
        exports = { processEvent: myProcessEventFunction }  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
})

test('exports set', async () => {
    const indexJs = `
        function myProcessEventFunction (event, meta) {
            event.event = 'changed event';
            return event
        }
        exports.processEvent = myProcessEventFunction  
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('changed event')
})

test('meta.config', async () => {
    const indexJs = `
        async function processEvent (event, meta) {
            event.properties = meta.config
            return event
        }
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
        properties: {},
    }
    await vm.methods.processEvent(event)

    expect(event.properties).toEqual(mockConfig.config)
})

test('meta.cache set/get', async () => {
    const indexJs = `
        async function processEvent (event, meta) {
            const counter = await meta.cache.get('counter', 0)
            meta.cache.set('counter', counter + 1)
            event.properties['counter'] = counter + 1
            return event
        }
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
        properties: {},
    }

    ;(mockServer.redis.get as any).mockResolvedValueOnce(10)

    await vm.methods.processEvent(event)
    expect(event.properties!['counter']).toEqual(11)

    expect(mockServer.redis.set).toHaveBeenCalledWith('@plugin/mock-plugin/2/counter', '11')
})

test('lib.js (deprecated)', async () => {
    const indexJs = `
        async function processEvent (event, meta) {
            event.event = libraryFunction(event.event)
            return event
        }
    `
    const libJs = `
        function libraryFunction (string) {
            return string.split("").reverse().join("")
        }
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs, libJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'original event',
    }
    await vm.methods.processEvent(event)

    expect(event.event).toEqual('tneve lanigiro')
})

test('console.log', async () => {
    console.log = jest.fn()
    console.error = jest.fn()
    console.warn = jest.fn()
    console.info = jest.fn()
    console.debug = jest.fn()
    const indexJs = `
        async function processEvent (event, meta) {
            console.log(event.event)
            console.error(event.event)
            console.warn(event.event)
            console.info(event.event)
            console.debug(event.event)
            return event
        }
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'logged event',
    }

    await vm.methods.processEvent(event)
    expect(console.log).toHaveBeenCalledWith('logged event')
    expect(console.error).toHaveBeenCalledWith('logged event')
    expect(console.warn).toHaveBeenCalledWith('logged event')
    expect(console.info).toHaveBeenCalledWith('logged event')
    expect(console.debug).toHaveBeenCalledWith('logged event')
})

test('fetch', async () => {
    const indexJs = `
        async function processEvent (event, meta) {
            const response = await fetch('https://google.com/results.json?query=' + event.event)
            event.properties = await response.json()
            return event             
        }
    `
    const vm = createPluginConfigVM(mockServer, mockConfig, indexJs)
    const event: PluginEvent = {
        ...defaultEvent,
        event: 'fetched',
    }

    await vm.methods.processEvent(event)
    expect(fetch).toHaveBeenCalledWith('https://google.com/results.json?query=fetched')

    expect(event.properties).toEqual({ count: 2, query: 'bla', results: [true, true] })
})

// attachments
// prepareForRun
