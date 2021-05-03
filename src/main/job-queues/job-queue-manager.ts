import * as Sentry from '@sentry/node'

import { EnqueuedRetry, JobQueue, OnRetryCallback, PluginsServer } from '../../types'
import { FsQueue } from './fs-queue'
import { GraphileQueue } from './graphile-queue'

enum JobQueueType {
    FS = 'fs',
    Graphile = 'graphile',
}

const queues: Record<JobQueueType, (server: PluginsServer) => JobQueue> = {
    fs: () => new FsQueue(),
    graphile: (pluginsServer: PluginsServer) => new GraphileQueue(pluginsServer),
}

export class JobQueueManager implements JobQueue {
    pluginsServer: PluginsServer
    jobQueues: JobQueue[]

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer

        this.jobQueues = pluginsServer.RETRY_QUEUES.split(',')
            .map((q) => q.trim() as JobQueueType)
            .filter((q) => !!q)
            .map(
                (queue): JobQueue => {
                    if (queues[queue]) {
                        return queues[queue](pluginsServer)
                    } else {
                        throw new Error(`Unknown retry queue "${queue}"`)
                    }
                }
            )
    }

    async enqueue(retry: EnqueuedRetry): Promise<void> {
        for (const retryQueue of this.jobQueues) {
            try {
                await retryQueue.enqueue(retry)
                return
            } catch (error) {
                // if one fails, take the next queue
                Sentry.captureException(error, {
                    extra: {
                        retry: JSON.stringify(retry),
                        queue: retryQueue.toString(),
                        queues: this.jobQueues.map((q) => q.toString()),
                    },
                })
            }
        }
        throw new Error('No JobQueue available')
    }

    async quit(): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.quit()))
    }

    async startConsumer(onRetry: OnRetryCallback): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.startConsumer(onRetry)))
    }

    async stopConsumer(): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.stopConsumer()))
    }

    async pauseConsumer(): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.pauseConsumer()))
    }

    isConsumerPaused(): boolean {
        return !!this.jobQueues.find((r) => r.isConsumerPaused())
    }

    async resumeConsumer(): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.resumeConsumer()))
    }
}
