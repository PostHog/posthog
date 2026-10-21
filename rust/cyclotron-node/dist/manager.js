"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CyclotronManager = void 0;
const cyclotron = require('../index.node');
const helpers_1 = require("./helpers");
class CyclotronManager {
    config;
    constructor(config) {
        this.config = config;
        this.config = config;
    }
    async connect() {
        const config = {
            shards: this.config.shards.map((shard) => (0, helpers_1.convertToInternalPoolConfig)(shard)),
            shardDepthLimit: this.config.shardDepthLimit,
            shardDepthCheckIntervalSeconds: this.config.shardDepthCheckIntervalSeconds,
            shouldCompressVmState: this.config.shouldCompressVmState,
            shouldUseBulkJobCopy: this.config.shouldUseBulkJobCopy,
        };
        return await cyclotron.maybeInitManager(JSON.stringify(config));
    }
    async createJob(job) {
        job.priority ??= 1;
        job.scheduled ??= new Date().toISOString();
        const jobInitInternal = {
            id: job.id,
            team_id: job.teamId,
            function_id: job.functionId,
            queue_name: job.queueName,
            priority: job.priority,
            scheduled: job.scheduled,
            vm_state: job.vmState ? (0, helpers_1.serializeObject)('vmState', job.vmState) : null,
            parameters: job.parameters ? (0, helpers_1.serializeObject)('parameters', job.parameters) : null,
            metadata: job.metadata ? (0, helpers_1.serializeObject)('metadata', job.metadata) : null,
        };
        const json = JSON.stringify(jobInitInternal);
        return await cyclotron.createJob(json, job.blob ? job.blob : undefined);
    }
    async bulkCreateJobs(jobs) {
        const jobInitsInternal = jobs.map((job) => {
            job.priority ??= 1;
            job.scheduled ??= new Date().toISOString();
            return {
                id: job.id,
                team_id: job.teamId,
                function_id: job.functionId,
                queue_name: job.queueName,
                priority: job.priority,
                scheduled: job.scheduled,
                vm_state: job.vmState ? (0, helpers_1.serializeObject)('vmState', job.vmState) : null,
                parameters: job.parameters ? (0, helpers_1.serializeObject)('parameters', job.parameters) : null,
                metadata: job.metadata ? (0, helpers_1.serializeObject)('metadata', job.metadata) : null,
            };
        });
        const json = JSON.stringify(jobInitsInternal);
        const totalBytes = jobs.reduce((total, job) => total + (job.blob ? job.blob.byteLength : 0), 0);
        const blobs = new Uint8Array(totalBytes);
        const blobLengths = new Uint32Array(jobs.length);
        let offset = 0;
        for (let i = 0; i < jobs.length; i++) {
            const blob = jobs[i].blob;
            if (blob) {
                blobLengths[i] = blob.byteLength;
                blobs.set(blob, offset);
                offset += blob.byteLength;
            }
            else {
                blobLengths[i] = 0;
            }
        }
        return await cyclotron.bulkCreateJobs(json, blobs, blobLengths);
    }
}
exports.CyclotronManager = CyclotronManager;
//# sourceMappingURL=manager.js.map