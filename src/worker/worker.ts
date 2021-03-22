import * as Sentry from '@sentry/node'

import { initApp } from '../init'
import { createServer } from '../shared/server'
import { status } from '../shared/status'
import { cloneObject } from '../shared/utils'
import { PluginsServer, PluginsServerConfig } from '../types'
import { ingestEvent } from './ingestion/ingest-event'
import { runPlugins, runPluginsOnBatch, runPluginTask } from './plugins/run'
import { loadSchedule, setupPlugins } from './plugins/setup'

type TaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig, threadId: number): Promise<TaskWorker> {
    initApp(config)

    status.info('🧵', `Starting Piscina worker thread ${threadId}…`)

    const [server, closeServer] = await createServer(config, threadId)
    await setupPlugins(server)

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, closeServer)
    }

    return createTaskRunner(server)
}

export const createTaskRunner = (server: PluginsServer): TaskWorker => async ({ task, args }) => {
    const timer = new Date()
    let response

    Sentry.setContext('task', { task, args })

    if (task === 'hello') {
        response = `hello ${args[0]}!`
    }
    if (task === 'processEvent') {
        const processedEvent = await runPlugins(server, args.event)
        // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
        response = cloneObject(processedEvent as Record<string, any>)
    }
    if (task === 'processEventBatch') {
        const processedEvents = await runPluginsOnBatch(server, args.batch)
        // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
        response = cloneObject(processedEvents as any[])
    }
    if (task === 'getPluginSchedule') {
        response = cloneObject(server.pluginSchedule)
    }
    if (task === 'ingestEvent') {
        response = cloneObject(await ingestEvent(server, args.event))
    }
    if (task.startsWith('runEvery')) {
        const { pluginConfigId } = args
        response = cloneObject(await runPluginTask(server, task, pluginConfigId))
    }
    if (task === 'reloadPlugins') {
        await setupPlugins(server)
    }
    if (task === 'reloadSchedule') {
        await loadSchedule(server)
    }
    if (task === 'flushKafkaMessages') {
        await server.db.flushKafkaMessages()
    }
    server.statsd?.timing(`piscina_task.${task}`, timer)
    return response
}
