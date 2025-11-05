// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')
import { convertToInternalPoolConfig, deserializeObject, serializeObject } from './helpers'
import {
    CyclotronJob,
    CyclotronJobState,
    CyclotronJobUpdate,
    CyclotronPoolConfig,
} from './types'

const parseJob = (job: CyclotronJob): CyclotronJob => {
    return {
        ...job,
        vmState: deserializeObject('vmState', job.vmState),
        metadata: deserializeObject('metadata', job.metadata),
        parameters: deserializeObject('parameters', job.parameters),
    }
}

// Config specific to the node worker
type CyclotronWorkerNodeConfig = {
    pool: CyclotronPoolConfig
    /** The queue to be consumed from */
    queueName: string
    /** Max number of jobs to consume in a batch. Default: 100 */
    batchMaxSize?: number
    /** Whether the vmState will be included or not */
    includeVmState?: boolean
    /** Amount of delay between dequeue polls. Default: 50ms */
    pollDelayMs?: number
    /** Heartbeat timeout. After this time without response from the worker loop the worker will be considered unhealthy. Default 30000 */
    heartbeatTimeoutMs?: number
    /** Include empty batches - useful if you want to track them. Default: false */
    includeEmptyBatches?: boolean
}


type CyclotronWorkerInternalConfig = {
    /** Heartbeat timeout. After this time without response from the worker loop the worker will be considered unhealthy. Default 30000 */
    heartbeatTimeoutMs?: number
    /** Heartbeat window. Default 5 */
    heartbeatWindowSeconds?: number
    /** Linger time. Default 500 */
    lingerTimeMs?: number
    /** Max updates buffered. Default 100 */
    maxUpdatesBuffered?: number
    /** Max bytes buffered. Default 10MB */
    maxBytesBuffered?: number
    /** Flush loop interval. Default 10 */
    flushLoopIntervalMs?: number
    /** Whether to compress vmState. Default false */
    shouldCompressVmState?: boolean
}


export type CyclotronWorkerConfig = CyclotronWorkerNodeConfig & CyclotronWorkerInternalConfig

export class CyclotronWorker {
    isConsuming: boolean = false
    lastHeartbeat: Date = new Date()

    private consumerLoopPromise: Promise<void> | null = null

    constructor(private config: CyclotronWorkerConfig) {}

    public isHealthy(): boolean {
        return (
            this.isConsuming &&
            new Date().getTime() - this.lastHeartbeat.getTime() < (this.config.heartbeatTimeoutMs ?? 30000)
        )
    }

    async connect(processBatch: (jobs: CyclotronJob[]) => Promise<void>): Promise<void> {
        if (this.isConsuming) {
            throw new Error('Already consuming')
        }

        const config: CyclotronWorkerInternalConfig = {
            heartbeatWindowSeconds: this.config.heartbeatWindowSeconds ?? 5,
            lingerTimeMs: this.config.lingerTimeMs ?? 500,
            maxUpdatesBuffered: this.config.maxUpdatesBuffered ?? 100,
            maxBytesBuffered: this.config.maxBytesBuffered ?? 10000000,
            flushLoopIntervalMs: this.config.flushLoopIntervalMs ?? 10,
            shouldCompressVmState: this.config.shouldCompressVmState ?? false,
        }

        await cyclotron.maybeInitWorker(
            JSON.stringify(convertToInternalPoolConfig(this.config.pool)),
            JSON.stringify(config)
        )

        this.isConsuming = true
        this.consumerLoopPromise = this.startConsumerLoop(processBatch).finally(() => {
            this.isConsuming = false
            this.consumerLoopPromise = null
        })
    }

    private async startConsumerLoop(processBatch: (jobs: CyclotronJob[]) => Promise<void>): Promise<void> {
        try {
            this.isConsuming = true

            const batchMaxSize = this.config.batchMaxSize ?? 100
            const pollDelayMs = this.config.pollDelayMs ?? 50

            while (this.isConsuming) {
                this.lastHeartbeat = new Date()

                const jobs = (
                    this.config.includeVmState
                        ? await cyclotron.dequeueJobsWithVmState(this.config.queueName, batchMaxSize)
                        : await cyclotron.dequeueJobs(this.config.queueName, batchMaxSize)
                ).map(parseJob)

                if (!jobs.length) {
                    // Wait a bit before polling again
                    await new Promise((resolve) => setTimeout(resolve, pollDelayMs))
                    if (this.config.includeEmptyBatches) {
                        await processBatch(jobs)
                    }
                    continue
                }

                await processBatch(jobs)
            }
        } catch (e) {
            // We only log here so as not to crash the parent process
            console.error('[Cyclotron] Error in worker loop', e)
        }
    }

    async disconnect(): Promise<void> {
        this.isConsuming = false
        await (this.consumerLoopPromise ?? Promise.resolve())
    }

    async releaseJob(jobId: string): Promise<void> {
        // We hand the promise back to the user, letting them decide when to await it.
        return cyclotron.releaseJob(jobId)
    }

    updateJob(id: CyclotronJob['id'], state: CyclotronJobState, updates?: CyclotronJobUpdate): void {
        cyclotron.setState(id, state)
        if (updates?.queueName !== undefined) {
            cyclotron.setQueue(id, updates.queueName)
        }
        if (updates?.priority !== undefined) {
            cyclotron.setPriority(id, updates.priority)
        }
        if (updates?.parameters !== undefined) {
            cyclotron.setParameters(id, serializeObject('parameters', updates.parameters))
        }
        if (updates?.metadata !== undefined) {
            cyclotron.setMetadata(id, serializeObject('metadata', updates.metadata))
        }
        if (updates?.vmState !== undefined) {
            cyclotron.setVmState(id, serializeObject('vmState', updates.vmState))
        }
        if (updates?.blob !== undefined) {
            cyclotron.setBlob(id, updates.blob)
        }
        if (updates?.scheduled !== undefined) {
            cyclotron.setScheduledAt(id, updates.scheduled)
        }
    }
}
