import { CyclotronJobInit, CyclotronPoolConfig, CyclotronInternalPoolConfig } from './types';
type CyclotronManagerInternalConfig = {
    shards: CyclotronInternalPoolConfig[];
    shardDepthLimit?: number;
    shardDepthCheckIntervalSeconds?: number;
    shouldCompressVmState?: boolean;
    shouldUseBulkJobCopy?: boolean;
};
export type CyclotronManagerConfig = Omit<CyclotronManagerInternalConfig, 'shards'> & {
    shards: CyclotronPoolConfig[];
};
export declare class CyclotronManager {
    private config;
    constructor(config: CyclotronManagerConfig);
    connect(): Promise<void>;
    createJob(job: CyclotronJobInit): Promise<string>;
    bulkCreateJobs(jobs: CyclotronJobInit[]): Promise<string[]>;
}
export {};
