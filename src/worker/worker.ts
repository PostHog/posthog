import * as Sentry from '@sentry/node'

import { initApp } from '../init'
import { PluginsServer, PluginsServerConfig } from '../types'
import { processError } from '../utils/db/error'
import { createServer } from '../utils/db/server'
import { status } from '../utils/status'
import { cloneObject, pluginConfigIdFromStack } from '../utils/utils'
import { setupPlugins } from './plugins/setup'
import { workerTasks } from './tasks'

export type PiscinaTaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig, threadId: number): Promise<PiscinaTaskWorker> {
    initApp(config)

    status.info('🧵', `Starting Piscina worker thread ${threadId}…`)

    const [server, closeServer] = await createServer(config, threadId)
    await setupPlugins(server)

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, closeServer)
    }

    process.on('unhandledRejection', (error: Error) => processUnhandledRejections(error, server))

    return createTaskRunner(server)
}

export const createTaskRunner = (server: PluginsServer): PiscinaTaskWorker => async ({ task, args }) => {
    const timer = new Date()
    let response

    Sentry.setContext('task', { task, args })

    if (task in workerTasks) {
        try {
            // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
            response = cloneObject(await workerTasks[task](server, args))
        } catch (e) {
            status.info('🔔', e)
            Sentry.captureException(e)
            response = { error: e.message }
        }
    } else {
        response = { error: `Worker task "${task}" not found in: ${Object.keys(workerTasks).join(', ')}` }
    }

    server.statsd?.timing(`piscina_task.${task}`, timer)
    return response
}

export function processUnhandledRejections(error: Error, server: PluginsServer): void {
    const pluginConfigId = pluginConfigIdFromStack(error.stack || '', server.pluginConfigSecretLookup)
    const pluginConfig = pluginConfigId ? server.pluginConfigs.get(pluginConfigId) : null

    if (pluginConfig) {
        void processError(server, pluginConfig, error)
        return
    }

    Sentry.captureException(error, {
        extra: {
            type: 'Unhandled promise error in worker',
        },
    })

    status.error('🤮', `Unhandled Promise Error!`)
    status.error('🤮', error)
}
