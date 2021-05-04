import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { EnqueuedJob, PluginsServer, PluginTaskType } from '../types'
import { ingestEvent } from './ingestion/ingest-event'
import { runPlugins, runPluginsOnBatch, runPluginTask } from './plugins/run'
import { loadSchedule, setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'

type TaskRunner = (server: PluginsServer, args: any) => Promise<any> | any

export const workerTasks: Record<string, TaskRunner> = {
    hello: (server, args) => {
        return `hello ${args}!`
    },
    processEvent: (server, args: { event: PluginEvent }) => {
        return runPlugins(server, args.event)
    },
    processEventBatch: (server, args: { batch: PluginEvent[] }) => {
        return runPluginsOnBatch(server, args.batch)
    },
    runJob: (server, { job }: { job: EnqueuedJob }) => {
        return runPluginTask(server, job.type, PluginTaskType.Job, job.pluginConfigId, job.payload)
    },
    runEveryMinute: (server, args: { pluginConfigId: number }) => {
        return runPluginTask(server, 'runEveryMinute', PluginTaskType.Schedule, args.pluginConfigId)
    },
    runEveryHour: (server, args: { pluginConfigId: number }) => {
        return runPluginTask(server, 'runEveryHour', PluginTaskType.Schedule, args.pluginConfigId)
    },
    runEveryDay: (server, args: { pluginConfigId: number }) => {
        return runPluginTask(server, 'runEveryDay', PluginTaskType.Schedule, args.pluginConfigId)
    },
    getPluginSchedule: (server) => {
        return server.pluginSchedule
    },
    ingestEvent: async (server, args: { event: PluginEvent }) => {
        return await ingestEvent(server, args.event)
    },
    reloadPlugins: async (server) => {
        await setupPlugins(server)
    },
    reloadSchedule: async (server) => {
        await loadSchedule(server)
    },
    teardownPlugins: async (server) => {
        await teardownPlugins(server)
    },
    flushKafkaMessages: async (server) => {
        await server.kafkaProducer?.flush()
    },
}
