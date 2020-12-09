import * as yargs from 'yargs'
import { PluginsServerConfig } from './types'
import { startPluginsServer } from './server'
import { makePiscina } from './worker/piscina'
import { defaultConfig, configHelp } from './config'
import { initApp } from './init'

type Argv = {
    config: string
    disableWeb: boolean
    webPort: number
    webHostname: string
    concurrency: number
}

let app: any = yargs
    .wrap(yargs.terminalWidth())
    .scriptName('posthog-plugins')
    .option('config', { alias: 'c', describe: 'Config options JSON.', type: 'string' })

for (const [key, value] of Object.entries(defaultConfig)) {
    app = app.option(key.toLowerCase().split('_').join('-'), {
        describe: `${configHelp[key] || key} [${value}]`,
        type: typeof value,
    })
}

const { config: configArg, ...otherArgs }: Argv = app.help().argv

const configJson = configArg || process.env.CONFIG
const config: PluginsServerConfig = { ...defaultConfig, ...(configJson ? JSON.parse(configJson) : {}) }

for (const [key, value] of Object.entries(otherArgs)) {
    if (typeof value !== 'undefined') {
        // convert camelCase argument keys to under_score
        const newKey = key
            .replace(/(?:^|\.?)([A-Z])/g, (x, y) => '_' + y.toUpperCase())
            .replace(/^_/, '')
            .toUpperCase()
        if (newKey in defaultConfig) {
            config[newKey] = value
        }
    }
}

initApp(config)
startPluginsServer(config, makePiscina)
