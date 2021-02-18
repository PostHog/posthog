import { transform } from '@babel/standalone'

import { PluginsServer } from '../../types'
import { loopTimeout } from './loop-timeout'
import { promiseTimeout } from './promise-timeout'

export function secureCode(rawCode: string, server: PluginsServer): string {
    const { code } = transform(rawCode, {
        envName: 'production',
        code: true,
        babelrc: false,
        configFile: false,
        presets: [['env', { targets: { node: process.versions.node } }]],
        plugins: [loopTimeout(server), promiseTimeout(server)],
    })
    if (!code) {
        throw new Error(`Babel transform gone wrong! Could not secure the following code:\n${rawCode}`)
    }
    return code
}
