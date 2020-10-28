import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer, Plugin, PluginVM, VMMethod, PluginConfig, PluginEvent } from './types'
import { createCache } from './extensions/cache'
import { createInternalPostHogInstance } from 'posthog-js-lite'

export function createVm(plugin: Plugin, indexJs: string, libJs: string | null, server: PluginsServer) {
    const vm = new VM({
        sandbox: {},
    })
    vm.freeze(fetch, 'fetch') // Second argument adds object to global.
    vm.freeze(createConsole(), 'console')

    if (libJs) {
        vm.run(libJs)
    }
    vm.run(indexJs)

    const global = vm.run('global')

    return {
        vm,
        setupTeam: global.setupTeam,
        processEvent: global.processEvent || global.process_event,
    }
}

export function prepareForRun(
    server: PluginsServer,
    pluginVM: PluginVM,
    teamId: number,
    teamPlugin: PluginConfig,
    method: VMMethod,
    event?: PluginEvent
) {
    const { plugin, vm, [method]: pluginFunction } = pluginVM
    if (!pluginFunction) {
        return null
    }
    const meta = {
        team: teamPlugin.team_id,
        order: teamPlugin.order,
        name: plugin.name,
        tag: plugin.tag,
        config: teamPlugin.config,
    }

    vm.freeze(createCache(server, plugin.name, teamId), 'cache')

    if (event?.properties?.token) {
        const posthog = createInternalPostHogInstance(
            event.properties.token,
            { apiHost: event.site_url, fetch },
            {
                performance: require('perf_hooks').performance,
            }
        )
        vm.freeze(posthog, 'posthog')
    } else {
        vm.freeze(null, 'posthog')
    }

    if (method === 'processEvent') {
        return (event: PluginEvent) => pluginVM['processEvent'](event, meta)
    } else if (method === 'setupTeam') {
        return () => pluginVM['setupTeam'](meta)
    }
}
