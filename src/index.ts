#!/usr/bin/env node
import { setupPlugins } from './plugins'
import { worker } from './worker'
import { version } from '../package.json'

require('yargs')
    .scriptName('posthog-plugins')
    .command('start', 'start the server', (argv) => {
        console.info(`⚡ Starting posthog-plugins server v${version}!`)
        setupPlugins()
        worker.start()
    })
    .demandCommand()
    .help().argv
