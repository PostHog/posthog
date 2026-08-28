"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CyclotronWorker = void 0;
const cyclotron = require('../index.node');
const helpers_1 = require("./helpers");
const parseJob = (job) => {
    return {
        ...job,
        vmState: (0, helpers_1.deserializeObject)('vmState', job.vmState),
        metadata: (0, helpers_1.deserializeObject)('metadata', job.metadata),
        parameters: (0, helpers_1.deserializeObject)('parameters', job.parameters),
    };
};
class CyclotronWorker {
    config;
    isConsuming = false;
    lastHeartbeat = new Date();
    consumerLoopPromise = null;
    constructor(config) {
        this.config = config;
    }
    isHealthy() {
        return (this.isConsuming &&
            new Date().getTime() - this.lastHeartbeat.getTime() < (this.config.heartbeatTimeoutMs ?? 30000));
    }
    async connect(processBatch) {
        if (this.isConsuming) {
            throw new Error('Already consuming');
        }
        const config = {
            heartbeatWindowSeconds: this.config.heartbeatWindowSeconds ?? 5,
            lingerTimeMs: this.config.lingerTimeMs ?? 500,
            maxUpdatesBuffered: this.config.maxUpdatesBuffered ?? 100,
            maxBytesBuffered: this.config.maxBytesBuffered ?? 10000000,
            flushLoopIntervalMs: this.config.flushLoopIntervalMs ?? 10,
            shouldCompressVmState: this.config.shouldCompressVmState ?? false,
        };
        await cyclotron.maybeInitWorker(JSON.stringify((0, helpers_1.convertToInternalPoolConfig)(this.config.pool)), JSON.stringify(config));
        this.isConsuming = true;
        this.consumerLoopPromise = this.startConsumerLoop(processBatch).finally(() => {
            this.isConsuming = false;
            this.consumerLoopPromise = null;
        });
    }
    async startConsumerLoop(processBatch) {
        try {
            this.isConsuming = true;
            const batchMaxSize = this.config.batchMaxSize ?? 100;
            const pollDelayMs = this.config.pollDelayMs ?? 50;
            while (this.isConsuming) {
                this.lastHeartbeat = new Date();
                const jobs = (this.config.includeVmState
                    ? await cyclotron.dequeueJobsWithVmState(this.config.queueName, batchMaxSize)
                    : await cyclotron.dequeueJobs(this.config.queueName, batchMaxSize)).map(parseJob);
                if (!jobs.length) {
                    await new Promise((resolve) => setTimeout(resolve, pollDelayMs));
                    if (this.config.includeEmptyBatches) {
                        await processBatch(jobs);
                    }
                    continue;
                }
                await processBatch(jobs);
            }
        }
        catch (e) {
            console.error('[Cyclotron] Error in worker loop', e);
        }
    }
    async disconnect() {
        this.isConsuming = false;
        await (this.consumerLoopPromise ?? Promise.resolve());
    }
    async releaseJob(jobId) {
        return cyclotron.releaseJob(jobId);
    }
    updateJob(id, state, updates) {
        cyclotron.setState(id, state);
        if (updates?.queueName !== undefined) {
            cyclotron.setQueue(id, updates.queueName);
        }
        if (updates?.priority !== undefined) {
            cyclotron.setPriority(id, updates.priority);
        }
        if (updates?.parameters !== undefined) {
            cyclotron.setParameters(id, (0, helpers_1.serializeObject)('parameters', updates.parameters));
        }
        if (updates?.metadata !== undefined) {
            cyclotron.setMetadata(id, (0, helpers_1.serializeObject)('metadata', updates.metadata));
        }
        if (updates?.vmState !== undefined) {
            cyclotron.setVmState(id, (0, helpers_1.serializeObject)('vmState', updates.vmState));
        }
        if (updates?.blob !== undefined) {
            cyclotron.setBlob(id, updates.blob);
        }
        if (updates?.scheduled !== undefined) {
            cyclotron.setScheduledAt(id, updates.scheduled);
        }
    }
}
exports.CyclotronWorker = CyclotronWorker;
//# sourceMappingURL=worker.js.map