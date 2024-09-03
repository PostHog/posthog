// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')

import { convertToInternalPoolConfig, serializeObject } from './helpers'
import { CyclotronJobInit, CyclotronPoolConfig } from './types'

export class CyclotronManager {
    constructor(private config: { shards: CyclotronPoolConfig[] }) {
        this.config = config
    }

    async connect(): Promise<void> {
        return await cyclotron.maybeInitManager(
            JSON.stringify({
                shards: this.config.shards.map((shard) => convertToInternalPoolConfig(shard)),
            })
        )
    }

    async createJob(job: CyclotronJobInit): Promise<void> {
        job.priority ??= 1
        job.scheduled ??= new Date()

        // TODO: Why is this type of job snake case whereas the dequeue return type is camel case?
        const jobInitInternal = {
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
        return await cyclotron.createJob(json, job.blob ? job.blob.buffer : undefined)
    }
}
