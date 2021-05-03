import * as Sentry from '@sentry/node'

import { EnqueuedRetry, OnRetryCallback, PluginsServer, RetryQueue } from '../../types'
import { FsQueue } from './fs-queue'
import { GraphileQueue } from './graphile-queue'

enum QueueType {
    FS = 'fs',
    Graphile = 'graphile',
}

const queues: Record<QueueType, (server: PluginsServer) => RetryQueue> = {
    fs: () => new FsQueue(),
    graphile: (pluginsServer: PluginsServer) => new GraphileQueue(pluginsServer),
}

export class RetryQueueManager implements RetryQueue {
    pluginsServer: PluginsServer
    retryQueues: RetryQueue[]

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer

        this.retryQueues = pluginsServer.RETRY_QUEUES.split(',')
            .map((q) => q.trim() as QueueType)
            .filter((q) => !!q)
            .map(
                (queue): RetryQueue => {
                    if (queues[queue]) {
                        return queues[queue](pluginsServer)
                    } else {
                        throw new Error(`Unknown retry queue "${queue}"`)
                    }
                }
            )
    }

    async enqueue(retry: EnqueuedRetry): Promise<void> {
        for (const retryQueue of this.retryQueues) {
            try {
                await retryQueue.enqueue(retry)
                return
            } catch (error) {
                // if one fails, take the next queue
                Sentry.captureException(error, {
                    extra: {
                        retry: JSON.stringify(retry),
                        queue: retryQueue.toString(),
                        queues: this.retryQueues.map((q) => q.toString()),
                    },
                })
            }
        }
        throw new Error('No RetryQueue available')
    }

    async quit(): Promise<void> {
        await Promise.all(this.retryQueues.map((r) => r.quit()))
    }

    async startConsumer(onRetry: OnRetryCallback): Promise<void> {
        await Promise.all(this.retryQueues.map((r) => r.startConsumer(onRetry)))
    }

    async stopConsumer(): Promise<void> {
        await Promise.all(this.retryQueues.map((r) => r.stopConsumer()))
    }

    async pauseConsumer(): Promise<void> {
        await Promise.all(this.retryQueues.map((r) => r.pauseConsumer()))
    }

    isConsumerPaused(): boolean {
        return !!this.retryQueues.find((r) => r.isConsumerPaused())
    }

    async resumeConsumer(): Promise<void> {
        await Promise.all(this.retryQueues.map((r) => r.resumeConsumer()))
    }
}
