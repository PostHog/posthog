import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer, PluginConfig, PluginConfigVMReponse } from './types'
import { PluginEvent } from 'posthog-plugins'
import { createCache } from './extensions/cache'
import { createInternalPostHogInstance } from 'posthog-js-lite'
import { performance } from 'perf_hooks'

function areWeTestingWithJest() {
    return process.env.JEST_WORKER_ID !== undefined
}

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
    if (areWeTestingWithJest()) {
        vm.freeze(setTimeout, '__jestSetTimeout')
    }
    vm.freeze(
        {
            cache: createCache(
                server,
                pluginConfig.plugin?.name || pluginConfig.plugin_id.toString(),
                pluginConfig.team_id
            ),
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
        
        // we have processEvent, but not processEventBatch
        if (!__getExported('processEventBatch') && __getExported('processEvent')) {
            exports.processEventBatch = async function processEventBatch (batch, meta) {
                const processEvent = __getExported('processEvent');
                let waitFor = false
                const processedEvents = batch.map(event => {
                    const e = processEvent(event, meta)
                    if (e && typeof e.then !== 'undefined') {
                        waitFor = true
                    }
                    return e
                })
                const response = waitFor ? (await Promise.all(processedEvents)) : processedEvents;
                return response.filter(r => r)
            }
        // we have processEventBatch, but not processEvent
        } else if (!__getExported('processEvent') && __getExported('processEventBatch')) {
            exports.processEvent = async function processEvent (event, meta) {
                return (await (__getExported('processEventBatch'))([event], meta))?.[0]
            }
        }
        
        // export various functions
        const __methods = {
            processEvent: __bindMeta('processEvent'),
            processEventBatch: __bindMeta('processEventBatch')
        };
        `
    )

    return {
        vm,
        methods: vm.run('__methods'),
    }
}
