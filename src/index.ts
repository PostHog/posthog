import { PluginsServerConfig } from './types'
import { startPluginsServer } from './server'
import yargs from 'yargs'

yargs
    .scriptName('posthog-plugins')
    .option('config', { alias: 'c', describe: 'json string of config options', type: 'string' })
    .command('start', 'start the server', ({ argv }) => {
        startPluginsServer(argv.config ? JSON.parse(argv.config) : {})
    })
    .demandCommand()
    .help().argv
