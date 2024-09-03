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

export class CyclotronWorker {
    constructor(private config: PoolConfig) {
        this.config = config
    }

    async connect(): Promise<void> {
        return await cyclotron.maybeInitWorker(JSON.stringify(convertToInternalPoolConfig(this.config)))
    }

    async dequeueJobs(queueName: string, limit: number): Promise<Job[]> {
        return (await cyclotron.dequeueJobs(queueName, limit)).map(parseJob)
    }

    async dequeueJobsWithVmState(queueName: string, limit: number): Promise<Job[]> {
        return (await cyclotron.dequeueJobsWithVmState(queueName, limit)).map(parseJob)
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
            cyclotron.setMetadata(id, updates.metadata)
        }

        if (updates?.vmState) {
            cyclotron.setMetadata(id, updates.metadata)
        }
    }

    // setState(jobId: string, jobState: JobState): void {
    //     return cyclotron.setState(jobId, jobState)
    // }

    // setQueue(jobId: string, queueName: string): void {
    //     return cyclotron.setQueue(jobId, queueName)
    // }

    // setPriority(jobId: string, priority: number): void {
    //     return cyclotron.setPriority(jobId, priority)
    // }

    // setScheduledAt(jobId: string, scheduledAt: Date): void {
    //     return cyclotron.setScheduledAt(jobId, scheduledAt.toISOString())
    // }

    // setVmState(jobId: string, vmState: Record<string, any> | null): void {
    //     const serialized = serializeObject('vmState', vmState)
    //     return cyclotron.setVmState(jobId, serialized)
    // }

    // setMetadata(jobId: string, metadata: Record<string, any> | null): void {
    //     const serialized = serializeObject('metadata', metadata)
    //     return cyclotron.setMetadata(jobId, serialized)
    // }

    // setParameters(jobId: string, parameters: Record<string, any> | null): void {
    //     const serialized = serializeObject('parameters', parameters)
    //     return cyclotron.setParameters(jobId, serialized)
    // }

    // setBlob(jobId: string, blob: Uint8Array | null): void {
    //     return cyclotron.setBlob(jobId, blob)
    // }
}
