// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')

import { convertToInternalPoolConfig, serializeObject } from './helpers'
import { CyclotronJobInit, CyclotronPoolConfig, CyclotronInternalPoolConfig } from './types'

type CyclotronManagerInternalConfig = {
    shards: CyclotronInternalPoolConfig[]
    shardDepthLimit?: number
    shardDepthCheckIntervalSeconds?: number
    shouldCompressVmState?: boolean
    shouldUseBulkJobCopy?: boolean
}

export type CyclotronManagerConfig = Omit<CyclotronManagerInternalConfig, 'shards'> & {
    shards: CyclotronPoolConfig[]
}

export class CyclotronManager {
    constructor(private config: CyclotronManagerConfig) {
        this.config = config
    }

    async connect(): Promise<void> {
        const config: CyclotronManagerInternalConfig = {
            shards: this.config.shards.map((shard) => convertToInternalPoolConfig(shard)),
            shardDepthLimit: this.config.shardDepthLimit,
            shardDepthCheckIntervalSeconds: this.config.shardDepthCheckIntervalSeconds,
            shouldCompressVmState: this.config.shouldCompressVmState,
            shouldUseBulkJobCopy: this.config.shouldUseBulkJobCopy,
        }
        return await cyclotron.maybeInitManager(JSON.stringify(config))
    }

    async createJob(job: CyclotronJobInit): Promise<string> {
        job.priority ??= 1
        job.scheduled ??= new Date().toISOString()

        // TODO: Why is this type of job snake case whereas the dequeue return type is camel case?
        const jobInitInternal = {
            id: job.id,
            team_id: job.teamId,
            function_id: job.functionId,
            queue_name: job.queueName,
            priority: job.priority,
            scheduled: job.scheduled,
            vm_state: job.vmState ? serializeObject('vmState', job.vmState) : null,
            parameters: job.parameters ? serializeObject('parameters', job.parameters) : null,
            metadata: job.metadata ? serializeObject('metadata', job.metadata) : null,
        }

        const json = JSON.stringify(jobInitInternal)
        return await cyclotron.createJob(json, job.blob ? job.blob : undefined)
    }

    async bulkCreateJobs(jobs: CyclotronJobInit[]): Promise<string[]> {
        const jobInitsInternal = jobs.map((job) => {
            job.priority ??= 1
            job.scheduled ??= new Date().toISOString()

            return {
                id: job.id,
                team_id: job.teamId,
                function_id: job.functionId,
                queue_name: job.queueName,
                priority: job.priority,
                scheduled: job.scheduled,
                vm_state: job.vmState ? serializeObject('vmState', job.vmState) : null,
                parameters: job.parameters ? serializeObject('parameters', job.parameters) : null,
                metadata: job.metadata ? serializeObject('metadata', job.metadata) : null,
            }
        })
        const json = JSON.stringify(jobInitsInternal)

        const totalBytes = jobs.reduce((total, job) => total + (job.blob ? job.blob.byteLength : 0), 0)

        // The cyclotron API expects a single buffer with all the blobs concatenated, and an array of lengths.
        // 0 lengths indicate that the job has no blob.
        const blobs = new Uint8Array(totalBytes)
        const blobLengths = new Uint32Array(jobs.length)

        let offset = 0
        for (let i = 0; i < jobs.length; i++) {
            const blob = jobs[i].blob
            if (blob) {
                blobLengths[i] = blob.byteLength
                blobs.set(blob, offset)
                offset += blob.byteLength
            } else {
                blobLengths[i] = 0
            }
        }

        return await cyclotron.bulkCreateJobs(json, blobs, blobLengths)
    }
}
