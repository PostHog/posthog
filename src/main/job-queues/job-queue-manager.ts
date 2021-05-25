import * as Sentry from '@sentry/node'

import { EnqueuedJob, Hub, JobQueue, OnJobCallback } from '../../types'
import { status } from '../../utils/status'
import { logOrThrowJobQueueError } from '../../utils/utils'
import { FsQueue } from './fs-queue'
import { GraphileQueue } from './graphile-queue'

enum JobQueueType {
    FS = 'fs',
    Graphile = 'graphile',
}

const queues: Record<JobQueueType, (server: Hub) => JobQueue> = {
    fs: () => new FsQueue(),
    graphile: (pluginsServer: Hub) => new GraphileQueue(pluginsServer),
}

export class JobQueueManager implements JobQueue {
    pluginsServer: Hub
    jobQueues: JobQueue[]
    jobQueueTypes: JobQueueType[]

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer

        this.jobQueueTypes = pluginsServer.JOB_QUEUES.split(',')
            .map((q) => q.trim() as JobQueueType)
            .filter((q) => !!q)

        this.jobQueues = this.jobQueueTypes.map(
            (queue): JobQueue => {
                if (queues[queue]) {
                    return queues[queue](pluginsServer)
                } else {
                    throw new Error(`Unknown job queue "${queue}"`)
                }
            }
        )
    }

    async connectProducer(): Promise<void> {
        const toRemove = new Set<JobQueue>()
        await Promise.all(
            this.jobQueues.map(async (jobQueue, index) => {
                const jobQueueType = this.jobQueueTypes[index]
                try {
                    await jobQueue.connectProducer()
                    status.info('🚶', `Connected to job queue producer "${jobQueueType}"`)
                } catch (error) {
                    toRemove.add(jobQueue)
                    logOrThrowJobQueueError(
                        this.pluginsServer,
                        error,
                        `Can not start job queue producer "${jobQueueType}": ${error.message}`
                    )
                }
            })
        )
        if (toRemove.size > 0) {
            this.jobQueues = this.jobQueues.filter((jobQueue) => !toRemove.has(jobQueue))
        }
    }

    async enqueue(job: EnqueuedJob): Promise<void> {
        for (const jobQueue of this.jobQueues) {
            try {
                await jobQueue.enqueue(job)
                return
            } catch (error) {
                // if one fails, take the next queue
                Sentry.captureException(error, {
                    extra: {
                        job: JSON.stringify(job),
                        queue: jobQueue.toString(),
                        queues: this.jobQueues.map((q) => q.toString()),
                    },
                })
            }
        }
        throw new Error('No JobQueue available')
    }

    async disconnectProducer(): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.disconnectProducer()))
    }

    async startConsumer(onJob: OnJobCallback): Promise<void> {
        await Promise.all(this.jobQueues.map((r) => r.startConsumer(onJob)))
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

    getJobQueueTypesAsString(): string {
        return this.jobQueueTypes.join(',')
    }
}
