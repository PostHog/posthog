import { CyclotronJob, CyclotronJobState, CyclotronJobUpdate, CyclotronPoolConfig } from './types';
type CyclotronWorkerNodeConfig = {
    pool: CyclotronPoolConfig;
    queueName: string;
    batchMaxSize?: number;
    includeVmState?: boolean;
    pollDelayMs?: number;
    heartbeatTimeoutMs?: number;
    includeEmptyBatches?: boolean;
};
type CyclotronWorkerInternalConfig = {
    heartbeatTimeoutMs?: number;
    heartbeatWindowSeconds?: number;
    lingerTimeMs?: number;
    maxUpdatesBuffered?: number;
    maxBytesBuffered?: number;
    flushLoopIntervalMs?: number;
    shouldCompressVmState?: boolean;
};
export type CyclotronWorkerConfig = CyclotronWorkerNodeConfig & CyclotronWorkerInternalConfig;
export declare class CyclotronWorker {
    private config;
    isConsuming: boolean;
    lastHeartbeat: Date;
    private consumerLoopPromise;
    constructor(config: CyclotronWorkerConfig);
    isHealthy(): boolean;
    connect(processBatch: (jobs: CyclotronJob[]) => Promise<void>): Promise<void>;
    private startConsumerLoop;
    disconnect(): Promise<void>;
    releaseJob(jobId: string): Promise<void>;
    updateJob(id: CyclotronJob['id'], state: CyclotronJobState, updates?: CyclotronJobUpdate): void;
}
export {};
