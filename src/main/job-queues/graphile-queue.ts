import { makeWorkerUtils, run, Runner, WorkerUtils, WorkerUtilsOptions } from 'graphile-worker'

import { EnqueuedRetry, JobQueue, OnRetryCallback, PluginsServer } from '../../types'

export class GraphileQueue implements JobQueue {
    pluginsServer: PluginsServer
    started: boolean
    paused: boolean
    onRetry: OnRetryCallback | null
    runner: Runner | null
    workerUtils: WorkerUtils | null

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer
        this.started = false
        this.paused = false
        this.onRetry = null
        this.runner = null
        this.workerUtils = null
    }

    async enqueue(retry: EnqueuedRetry): Promise<void> {
        if (!this.workerUtils) {
            this.workerUtils = await makeWorkerUtils(
                this.pluginsServer.RETRY_QUEUE_GRAPHILE_URL
                    ? {
                          connectionString: this.pluginsServer.RETRY_QUEUE_GRAPHILE_URL,
                      }
                    : ({
                          pgPool: this.pluginsServer.postgres,
                      } as WorkerUtilsOptions)
            )
            await this.workerUtils.migrate()
        }
        await this.workerUtils.addJob('retryTask', retry, { runAt: new Date(retry.timestamp), maxAttempts: 1 })
    }

    async quit(): Promise<void> {
        const oldWorkerUtils = this.workerUtils
        this.workerUtils = null
        await oldWorkerUtils?.release()
    }

    async startConsumer(onRetry: OnRetryCallback): Promise<void> {
        this.started = true
        this.onRetry = onRetry
        await this.syncState()
    }

    async stopConsumer(): Promise<void> {
        this.started = false
        await this.syncState()
    }

    async pauseConsumer(): Promise<void> {
        this.paused = true
        await this.syncState()
    }

    isConsumerPaused(): boolean {
        return this.paused
    }

    async resumeConsumer(): Promise<void> {
        this.paused = false
        await this.syncState()
    }

    async syncState(): Promise<void> {
        if (this.started && !this.paused) {
            if (!this.runner) {
                this.runner = await run({
                    connectionString: this.pluginsServer.DATABASE_URL,
                    concurrency: 1,
                    // Install signal handlers for graceful shutdown on SIGINT, SIGTERM, etc
                    noHandleSignals: false,
                    pollInterval: 100,
                    // you can set the taskList or taskDirectory but not both
                    taskList: {
                        retryTask: (payload) => {
                            void this.onRetry?.([payload as EnqueuedRetry])
                        },
                    },
                })
            }
        } else {
            if (this.runner) {
                const oldRunner = this.runner
                this.runner = null
                await oldRunner?.stop()
            }
        }
    }
}
