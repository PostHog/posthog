import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer, PluginConfig, PluginConfigVMReponse } from './types'
import { PluginEvent } from 'posthog-plugins'
import { createCache } from './extensions/cache'
import { createInternalPostHogInstance } from 'posthog-js-lite'
import { performance } from 'perf_hooks'

export function createPluginConfigVM(
    server: PluginsServer,
    pluginConfig: PluginConfig, // NB! might have team_id = 0
    indexJs: string,
    libJs: string | null
): PluginConfigVMReponse {
    const vm = new VM({
        sandbox: {},
    })
    vm.freeze(createConsole(), 'console')
    vm.freeze(fetch, 'fetch')

    vm.run('const exports = {};')
    vm.run('const __pluginLocalMeta = { global: {} };')
    vm.freeze(
        {
            cache: createCache(server, pluginConfig.plugin.name, pluginConfig.team_id),
            config: pluginConfig.config,
            attachments: pluginConfig.attachments,
        },
        '__pluginHostMeta'
    )
    vm.run(`const __pluginMeta = { ...__pluginHostMeta, ...__pluginLocalMeta };`)
    vm.run(`${libJs} ; ${indexJs}`)
    // remain backwards compatible with 1) compiled and non-compiled js, 2) setupPlugin and old setupTeam
    vm.run(`;global.setupPlugin 
            ? global.setupPlugin(__pluginMeta) 
            : exports.setupPlugin 
                ? exports.setupPlugin(__pluginMeta) 
                : global.setupTeam 
                    ? global.setupTeam(__pluginMeta) 
                    : exports.setupTeam 
                        ? exports.setupTeam(__pluginMeta) 
                        : false;`)

    const global = vm.run('global')
    const exports = vm.run('exports')

    vm.run(`
    const __methods = {
        processEvent: exports.processEvent || global.processEvent ? (...args) => (exports.processEvent || global.processEvent)(...args, __pluginMeta) : null
    }`)

    return {
        vm,
        methods: vm.run('__methods'),
    }
}

export function prepareForRun(
    server: PluginsServer,
    teamId: number,
    pluginConfig: PluginConfig, // might have team_id=0
    method: 'processEvent',
    event?: PluginEvent
): null | ((event: PluginEvent) => PluginEvent) | (() => void) {
    if (!pluginConfig.vm?.methods[method]) {
        return null
    }
    
    const { vm } = pluginConfig.vm

    if (event?.properties?.token) {
        // TODO: this should be nicer...
        const posthog = createInternalPostHogInstance(
            event.properties.token,
            { apiHost: event.site_url, fetch },
            {
                performance: performance,
            }
        )
        vm.freeze(posthog, 'posthog')
    } else {
        vm.freeze(null, 'posthog')
    }
    return pluginConfig.vm.methods[method]
}
