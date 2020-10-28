#!/usr/bin/env node
import { setupPlugins } from './plugins'
import { startWorker } from './worker'
import { version } from '../package.json'
import { PluginsServerConfig } from './types'

const defaultConfig: PluginsServerConfig = {
    CELERY_DEFAULT_QUEUE: 'celery',
    DATABASE_URL: 'postgres://localhost:5432/posthog',
    PLUGINS_CELERY_QUEUE: 'posthog-plugins',
    REDIS_URL: 'redis://localhost/',
    BASE_DIR: '.'
}

require('yargs')
    .scriptName('posthog-plugins')
    .command('start', 'start the server', ({ argv }) => {
        console.info(`⚡ Starting posthog-plugins server v${version}!`)

        const config: PluginsServerConfig = {
            ...defaultConfig,
            ...(argv.config ? JSON.parse(argv.config) : {}),
        }

        setupPlugins(config)
        startWorker(config)
    })
    .option('config', { alias: 'c', describe: 'json string of config options', type: 'string' })
    .demandCommand()
    .help().argv
