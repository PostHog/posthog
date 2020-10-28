import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer, Plugin } from './types'

export function createVm(plugin: Plugin, indexJs: string, libJs: string | null, server: PluginsServer) {
    const vm = new VM({
        sandbox: {}
    })
    vm.freeze(fetch, 'fetch'); // Second argument adds object to global.
    vm.freeze(createConsole(), 'console')

    if (libJs) {
        vm.run(libJs)
    }
    vm.run(indexJs)

    const global = vm.run('global')

    return {
        vm,
        processEvent: global.process_event
    }
}
