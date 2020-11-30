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
    libJs = ''
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
        // two ways packages could export themselves (plus "global")
        const module = { exports: {} };
        let exports = {};
        const __getExported = (key) => exports[key] || module.exports[key] || global[key]; 
        
        // the plugin JS code        
        ${libJs};
        ${indexJs};

        // inject the meta object + shareable 'global' to the end of each exported function
        const __pluginMeta = { 
            ...__pluginHostMeta, 
            global: {}
        };
        function __bindMeta (keyOrFunc) {
            const func = typeof keyOrFunc === 'function' ? keyOrFunc : __getExported(keyOrFunc);
            if (func) return (...args) => func(...args, __pluginMeta); 
        }
        function __callWithMeta (keyOrFunc, ...args) {
            const func = __bindMeta(keyOrFunc);
            if (func) return func(...args); 
        }
        
        // run the plugin setup script, if present
        __callWithMeta('setupPlugin');
        
        // export various functions
        const __methods = {
            processEvent: __bindMeta('processEvent')
        };
        `
    )

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
): null | ((event: PluginEvent) => Promise<PluginEvent>) | (() => void) {
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
