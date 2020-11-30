import yargs from 'yargs'
import { PluginsServerConfig } from './types'
import { startPluginsServer } from './server'

type Argv = {
    config: string
    disableWeb: boolean
    webPort: number
    webHostname: string
}

yargs
    .scriptName('posthog-plugins')
    .option('config', { alias: 'c', describe: 'Config options JSON.', type: 'string' })
    .option('disable-web', { describe: 'Whether web server should be disabled.', type: 'boolean' })
    .option('web-port', { alias: 'p', describe: 'Web server port.', type: 'number' })
    .option('web-hostname', { alias: 'h', describe: 'Web server hostname.', type: 'string' })
    .help()
    .command({
        command: ['start', '$0'],
        describe: 'start the server',
        handler: ({ config, disableWeb, webPort, webHostname }: Argv) => {
            const parsedConfig: PluginsServerConfig = {
                ...(config ? JSON.parse(config) : {}),
                WEB_HOSTNAME: webHostname,
                WEB_PORT: webPort,
                DISABLE_WEB: disableWeb,
            }
            startPluginsServer(parsedConfig)
        },
    }).argv
