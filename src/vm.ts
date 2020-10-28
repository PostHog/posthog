import { VM } from 'vm2'
import fetch from 'node-fetch'
import { createConsole } from './extensions/console'
import { PluginsServer } from './types'

export function createVm(plugin, indexJs: string, libJs: string, server: PluginsServer) {
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
