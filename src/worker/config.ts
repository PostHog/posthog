import { PluginsServerConfig } from '../types'
import { TaskQueue } from 'piscina/src/common'

// Copy From: node_modules/piscina/src/index.ts -- copied because it's not exported
interface Options {
    filename?: string | null
    minThreads?: number
    maxThreads?: number
    idleTimeout?: number
    maxQueue?: number | 'auto'
    concurrentTasksPerWorker?: number
    useAtomics?: boolean
    resourceLimits?: any
    argv?: string[]
    execArgv?: string[]
    env?: any
    workerData?: any
    taskQueue?: TaskQueue
    niceIncrement?: number
    trackUnmanagedFds?: boolean
}

export function createConfig(serverConfig: PluginsServerConfig, filename: string): Options {
    const config: Options = {
        filename,
        workerData: { serverConfig },
    }

    if (serverConfig.WORKER_CONCURRENCY && serverConfig.WORKER_CONCURRENCY > 0) {
        config.minThreads = serverConfig.WORKER_CONCURRENCY
        config.maxThreads = serverConfig.WORKER_CONCURRENCY
    }

    if (serverConfig.TASKS_PER_WORKER > 1) {
        config.concurrentTasksPerWorker = serverConfig.TASKS_PER_WORKER
    }

    return config
}
