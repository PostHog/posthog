import { VM, VMScript } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer, Plugin, PluginConfig, PluginScript, MetaAttachment } from './types'
import { PluginEvent } from 'posthog-plugins'
import { createCache } from './extensions/cache'
import { createInternalPostHogInstance } from 'posthog-js-lite'
import { performance } from 'perf_hooks'

interface PluginScriptReponse {
    plugin: Plugin
    script: VMScript
    setupTeam: boolean
    processEvent: boolean
}

export function createPluginScript(plugin: Plugin, indexJs: string, libJs: string | null): PluginScriptReponse {
    const vm = new VM({
        sandbox: {
            // exports: {}
        },
    })
    vm.run('const exports = {};')
    vm.freeze(createConsole(), 'console')

    const script = new VMScript(`${libJs} ; ${indexJs}`)
    script.compile()
    vm.run(script)

    const global = vm.run('global')
    const exports = vm.run('exports')

    return {
        plugin,
        script,
        setupTeam: !!(exports.setupTeam || global.setupTeam),
        processEvent: !!(exports.processEvent || global.processEvent),
    }
}

export function prepareForRun(
    server: PluginsServer,
    pluginScript: PluginScript,
    teamId: number,
    pluginConfig: PluginConfig, // might have team_id=0
    pluginAttachments: Record<string, MetaAttachment>,
    method: 'setupTeam' | 'processEvent',
    event?: PluginEvent
): null | ((event: PluginEvent) => PluginEvent) | (() => void) {
    if (!pluginScript) {
        return null
    }
    if (!pluginScript[method]) {
        return null
    }
    const { plugin } = pluginScript
    const meta = {
        team: pluginConfig.team_id,
        order: pluginConfig.order,
        name: plugin.name,
        tag: plugin.tag,
        config: pluginConfig.config,
        attachments: pluginAttachments,
    }

    const vm = new VM({
        sandbox: {},
    })
    vm.run('const exports = {};')
    vm.freeze(fetch, 'fetch') // Second argument adds object to global.
    vm.freeze(createConsole(), 'console')
    vm.freeze(createCache(server, plugin.name, teamId), 'cache')

    if (event?.properties?.token) {
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

    vm.run(pluginScript.script)

    const global = vm.run('global')
    const exports = vm.run('exports')

    if (method === 'processEvent') {
        return (event: PluginEvent) => (exports.processEvent || global.processEvent)(event, meta)
    } else if (method === 'setupTeam') {
        return () => (exports.setupTeam || global.setupTeam)(meta)
    }
    return null
}
