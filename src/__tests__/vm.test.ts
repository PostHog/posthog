import { createPluginConfigVM } from '../vm'
import { PluginConfig, PluginsServer, Plugin } from '../types'
import { PluginEvent } from 'posthog-plugins'
import { defaultConfig } from '../server'
import Redis from 'ioredis'
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
    config: {},
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
