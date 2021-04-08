import { initApp } from './init'
import { startPluginsServer } from './main/pluginsServer'
import { defaultConfig, formatConfigHelp } from './shared/config'
import { Status } from './shared/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Help = 'HELP',
    Version = 'VRSN',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--help') || argv.includes('-h')) {
    alternativeMode = AlternativeMode.Help
} else if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
}

const status = new Status(alternativeMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (alternativeMode) {
    case AlternativeMode.Version:
        break
    case AlternativeMode.Help:
        status.info('⚙️', `Supported configuration environment variables:\n${formatConfigHelp(7)}`)
        break
    default:
        initApp(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina) // void the returned promise
        break
}
