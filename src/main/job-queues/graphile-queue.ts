import { makeWorkerUtils, run, Runner, WorkerUtils, WorkerUtilsOptions } from 'graphile-worker'

import { EnqueuedJob, JobQueue, OnJobCallback, PluginsServer } from '../../types'

export class GraphileQueue implements JobQueue {
    pluginsServer: PluginsServer
    started: boolean
    paused: boolean
    onJob: OnJobCallback | null
    runner: Runner | null
    workerUtilsPromise: Promise<WorkerUtils> | null

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer
        this.started = false
        this.paused = false
        this.onJob = null
        this.runner = null
        this.workerUtilsPromise = null
    }

    async connectProducer(): Promise<void> {
        await (await this.getWorkerUtils()).migrate()
    }

    async enqueue(retry: EnqueuedJob): Promise<void> {
        await (await this.getWorkerUtils()).addJob('pluginJob', retry, {
            runAt: new Date(retry.timestamp),
            maxAttempts: 1,
        })
    }

    async disconnectProducer(): Promise<void> {
        const oldWorkerUtils = await this.workerUtilsPromise
        this.workerUtilsPromise = null
        await oldWorkerUtils?.release()
    }

    async startConsumer(onJob: OnJobCallback): Promise<void> {
        this.started = true
        this.onJob = onJob
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

    private async syncState(): Promise<void> {
        if (this.started && !this.paused) {
            if (!this.runner) {
                this.runner = await run({
                    ...this.getConnectionOptions(),
                    concurrency: 1,
                    // Install signal handlers for graceful shutdown on SIGINT, SIGTERM, etc
                    noHandleSignals: false,
                    pollInterval: 100,
                    // you can set the taskList or taskDirectory but not both
                    taskList: {
                        pluginJob: (payload) => {
                            void this.onJob?.([payload as EnqueuedJob])
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

    private getConnectionOptions(): Partial<WorkerUtilsOptions> {
        return this.pluginsServer.JOB_QUEUE_GRAPHILE_URL
            ? {
                  connectionString: this.pluginsServer.JOB_QUEUE_GRAPHILE_URL,
              }
            : ({
                  pgPool: this.pluginsServer.postgres,
              } as Partial<WorkerUtilsOptions>)
    }

    private async getWorkerUtils(): Promise<WorkerUtils> {
        if (!this.workerUtilsPromise) {
            this.workerUtilsPromise = makeWorkerUtils(this.getConnectionOptions())
        }
        return await this.workerUtilsPromise
    }
}
