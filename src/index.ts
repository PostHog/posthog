import { PluginsServerConfig } from './types'
import { startPluginsServer } from './server'

require('yargs')
    .scriptName('posthog-plugins')
    .command('start', 'start the server', ({ argv }: { argv: Record<string, any> }) => {
        const config: PluginsServerConfig = {
            ...(argv.config ? JSON.parse(argv.config) : {}),
        }
        startPluginsServer(config)
    })
    .option('config', { alias: 'c', describe: 'json string of config options', type: 'string' })
    .demandCommand()
    .help().argv
