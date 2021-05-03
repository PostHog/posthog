import { defaultConfig, formatConfigHelp } from './config/config'
import { initApp } from './init'
import { startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Help = 'HELP',
    Version = 'VRSN',
    Idle = 'IDLE',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--help') || argv.includes('-h')) {
    alternativeMode = AlternativeMode.Help
} else if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
} else if (defaultConfig.PLUGIN_SERVER_IDLE) {
    alternativeMode = AlternativeMode.Idle
}

const status = new Status(alternativeMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (alternativeMode) {
    case AlternativeMode.Version:
        break
    case AlternativeMode.Help:
        status.info('⚙️', `Supported configuration environment variables:\n${formatConfigHelp(7)}`)
        break
    case AlternativeMode.Idle:
        status.info('💤', `Disengaging this plugin server instance due to the PLUGIN_SERVER_IDLE env var...`)
        setInterval(() => {
            status.info('💤', 'Plugin server still disengaged with PLUGIN_SERVER_IDLE...')
        }, 30_000)
        break
    default:
        initApp(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina) // void the returned promise
        break
}
