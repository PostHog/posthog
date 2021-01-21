import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { createCache } from './extensions/cache'
import { createPosthog } from './extensions/posthog'
import { createGoogle } from './extensions/google'
import { PluginsServer, PluginConfig, PluginConfigVMReponse } from './types'
import { createStorage } from './extensions/storage'

export async function createPluginConfigVM(
    server: PluginsServer,
    pluginConfig: PluginConfig, // NB! might have team_id = 0
    indexJs: string,
    libJs = ''
): Promise<PluginConfigVMReponse> {
    const vm = new VM({
        sandbox: {},
    })

    // our own stuff
    vm.freeze(createConsole(), 'console')
    vm.freeze(createPosthog(server, pluginConfig), 'posthog')

    // exported node packages
    vm.freeze(fetch, 'fetch')
    vm.freeze(createGoogle(), 'google')

    if (process.env.NODE_ENV === 'test') {
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
            storage: createStorage(server, pluginConfig),
        },
        '__pluginHostMeta'
    )
    vm.run(
        `
        // two ways packages could export themselves (plus "global")
        const module = { exports: {} };
        let exports = {};

        // helpers to get globals
        const __getExportDestinations = () => [exports, module.exports, global]
        const __getExported = (key) => __getExportDestinations().find(a => a[key])?.[key];

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

        // gather the runEveryX commands and export in __tasks
        const __tasks = {};
        for (const exportDestination of __getExportDestinations().reverse()) {
            for (const [name, value] of Object.entries(exportDestination)) {
                if (name.startsWith("runEvery") && typeof value === 'function') {
                    __tasks[name] = {
                        name: name,
                        type: 'runEvery',
                        exec: __bindMeta(value)
                    }
                }
            }
        }

        // run the plugin setup script, if present
        const __setupPlugin = async () => __callWithMeta('setupPlugin');
        `
    )

    await vm.run('__setupPlugin')()

    return {
        vm,
        methods: vm.run('__methods'),
        tasks: vm.run('__tasks'),
    }
}
