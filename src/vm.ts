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
    vm.freeze(
        {
            cache: createCache(server, pluginConfig.plugin.name, pluginConfig.team_id),
            config: pluginConfig.config,
            attachments: pluginConfig.attachments,
        },
        '__pluginHostMeta'
    )
    vm.run(
        `
        const module = { exports: {} };
        const exports = {};
        const __pluginLocalMeta = { global: {} };
        const __pluginMeta = { ...__pluginHostMeta, ...__pluginLocalMeta };
        const __getGlobalWithMeta = (key) => {
            const method = exports[key] || module.exports[key] || global[key];
            if (!method) { return null };
            return (...args) => method(...args, __pluginMeta)
        } 
        `
    )
    vm.run(`${libJs} ; ${indexJs} ;`)
    vm.run(`(function () { const setupPlugin = __getGlobalWithMeta('setupPlugin'); setupPlugin && setupPlugin(); })();`)

    const global = vm.run('global')
    const exports = vm.run('exports')

    vm.run(`
    const __methods = {
        processEvent: __getGlobalWithMeta('processEvent')
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
