import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { EnqueuedJob, PluginsServer, PluginTaskType } from '../types'
import { ingestEvent } from './ingestion/ingest-event'
import { runOnEvent, runOnSnapshot, runPluginTask, runProcessEvent, runProcessEventBatch } from './plugins/run'
import { loadSchedule, setupPlugins } from './plugins/setup'
import { teardownPlugins } from './plugins/teardown'

type TaskRunner = (server: PluginsServer, args: any) => Promise<any> | any

export const workerTasks: Record<string, TaskRunner> = {
    hello: (server, args) => {
        return `hello ${args}!`
    },
    onEvent: (server, args: { event: PluginEvent }) => {
        return runOnEvent(server, args.event)
    },
    onSnapshot: (server, args: { event: PluginEvent }) => {
        return runOnSnapshot(server, args.event)
    },
    processEvent: (server, args: { event: PluginEvent }) => {
        return runProcessEvent(server, args.event)
    },
    processEventBatch: (server, args: { batch: PluginEvent[] }) => {
        return runProcessEventBatch(server, args.batch)
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
