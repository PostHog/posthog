// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')
import { convertToInternalPoolConfig, deserializeObject, serializeObject } from './helpers'
import { Job, JobState, JobUpdate, PoolConfig } from './types'

const parseJob = (job: Job): Job => {
    return {
        ...job,
        vmState: deserializeObject('vmState', job.vmState),
        metadata: deserializeObject('metadata', job.metadata),
        parameters: deserializeObject('parameters', job.parameters),
    }
}

export type CyclotronWorkerConfig = {
    pool: PoolConfig
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
}

export class CyclotronWorker {
    isConsuming: boolean = false
    lastHeartbeat: Date = new Date()

    private consumerLoopPromise: Promise<void> | null = null

    constructor(private config: CyclotronWorkerConfig) {
        this.config = config
    }

    public isHealthy(): boolean {
        return (
            this.isConsuming &&
            new Date().getTime() - this.lastHeartbeat.getTime() < (this.config.heartbeatTimeoutMs ?? 30000)
        )
    }

    async connect(processBatch: (jobs: Job[]) => Promise<void>): Promise<void> {
        if (this.isConsuming) {
            throw new Error('Already consuming')
        }

        await cyclotron.maybeInitWorker(JSON.stringify(convertToInternalPoolConfig(this.config.pool)))

        this.consumerLoopPromise = this.startConsumerLoop(processBatch)
    }

    private async startConsumerLoop(processBatch: (jobs: Job[]) => Promise<void>): Promise<void> {
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
                    continue
                }

                await processBatch(jobs)
            }
        } catch (e) {
            // We only log here so as not to crash the parent process
            console.error('Error in worker loop', e)
        } finally {
            this.isConsuming = false
        }
    }

    async disconnect(): Promise<void> {
        this.isConsuming = false
        await (this.consumerLoopPromise ?? Promise.resolve())
    }

    async flushJob(jobId: string): Promise<void> {
        return await cyclotron.flushJob(jobId)
    }

    updateJob(id: Job['id'], state: JobState, updates?: JobUpdate): void {
        cyclotron.setState(id, state)
        if (updates?.queueName) {
            cyclotron.setQueue(id, updates.queueName)
        }
        if (updates?.priority) {
            cyclotron.setPriority(id, updates.priority)
        }
        if (updates?.parameters) {
            cyclotron.setParameters(id, serializeObject('parameters', updates.parameters))
        }
        if (updates?.metadata) {
            cyclotron.setMetadata(id, serializeObject('metadata', updates.metadata))
        }
        if (updates?.vmState) {
            cyclotron.setVmState(id, serializeObject('vmState', updates.vmState))
        }
    }
}
