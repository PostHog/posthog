// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')

export interface PoolConfig {
    dbUrl: string
    maxConnections?: number
    minConnections?: number
    acquireTimeoutSeconds?: number
    maxLifetimeSeconds?: number
    idleTimeoutSeconds?: number
}

// Type as expected by Cyclotron.
interface InternalPoolConfig {
    db_url: string
    max_connections?: number
    min_connections?: number
    acquire_timeout_seconds?: number
    max_lifetime_seconds?: number
    idle_timeout_seconds?: number
}

export interface ManagerConfig {
    shards: PoolConfig[]
}

// Type as expected by Cyclotron.
interface InternalManagerConfig {
    shards: InternalPoolConfig[]
}

export interface JobInit {
    teamId: number
    functionId: string
    queueName: string
    priority?: number
    scheduled?: Date
    vmState?: string
    parameters?: string
    blob?: Uint8Array
    metadata?: string
}

// Type as expected by Cyclotron.
interface InternalJobInit {
    team_id: number
    function_id: string
    queue_name: string
    priority?: number
    scheduled?: Date
    vm_state?: string
    parameters?: string
    metadata?: string
}

export type JobState = 'available' | 'running' | 'completed' | 'failed' | 'paused'

export interface Job {
    id: string
    teamId: number
    functionId: string | null
    created: Date
    lockId: string | null
    lastHeartbeat: Date | null
    janitorTouchCount: number
    transitionCount: number
    lastTransition: Date
    queueName: string
    state: JobState
    priority: number
    scheduled: Date
    vmState: string | null
    metadata: string | null
    parameters: string | null
    blob: Uint8Array | null
}

async function initWorker(poolConfig: PoolConfig): Promise<void> {
    const initWorkerInternal: InternalPoolConfig = {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    }
    return await cyclotron.initWorker(JSON.stringify(initWorkerInternal))
}

async function initManager(managerConfig: ManagerConfig): Promise<void> {
    const managerConfigInternal: InternalManagerConfig = {
        shards: managerConfig.shards.map((shard) => ({
            db_url: shard.dbUrl,
            max_connections: shard.maxConnections,
            min_connections: shard.minConnections,
            acquire_timeout_seconds: shard.acquireTimeoutSeconds,
            max_lifetime_seconds: shard.maxLifetimeSeconds,
            idle_timeout_seconds: shard.idleTimeoutSeconds,
        })),
    }
    return await cyclotron.initManager(JSON.stringify(managerConfigInternal))
}

async function maybeInitWorker(poolConfig: PoolConfig): Promise<void> {
    const initWorkerInternal: InternalPoolConfig = {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    }
    return await cyclotron.maybeInitWorker(JSON.stringify(initWorkerInternal))
}

async function maybeInitManager(managerConfig: ManagerConfig): Promise<void> {
    const managerConfigInternal: InternalManagerConfig = {
        shards: managerConfig.shards.map((shard) => ({
            db_url: shard.dbUrl,
            max_connections: shard.maxConnections,
            min_connections: shard.minConnections,
            acquire_timeout_seconds: shard.acquireTimeoutSeconds,
            max_lifetime_seconds: shard.maxLifetimeSeconds,
            idle_timeout_seconds: shard.idleTimeoutSeconds,
        })),
    }
    return await cyclotron.maybeInitManager(JSON.stringify(managerConfigInternal))
}

async function createJob(job: JobInit): Promise<void> {
    job.priority ??= 1
    job.scheduled ??= new Date()

    const jobInitInternal: InternalJobInit = {
        team_id: job.teamId,
        function_id: job.functionId,
        queue_name: job.queueName,
        priority: job.priority,
        scheduled: job.scheduled,
        vm_state: job.vmState,
        parameters: job.parameters,
        metadata: job.metadata,
    }

    const json = JSON.stringify(jobInitInternal)
    return await cyclotron.createJob(json, job.blob ? job.blob.buffer : undefined)
}

async function dequeueJobs(queueName: string, limit: number): Promise<Job[]> {
    return await cyclotron.dequeueJobs(queueName, limit)
}

async function dequeueJobsWithVmState(queueName: string, limit: number): Promise<Job[]> {
    return await cyclotron.dequeueJobsWithVmState(queueName, limit)
}

async function flushJob(jobId: string): Promise<void> {
    return await cyclotron.flushJob(jobId)
}

function setState(jobId: string, jobState: JobState): Promise<void> {
    return cyclotron.setState(jobId, jobState)
}

function setQueue(jobId: string, queueName: string): Promise<void> {
    return cyclotron.setQueue(jobId, queueName)
}

function setPriority(jobId: string, priority: number): Promise<void> {
    return cyclotron.setPriority(jobId, priority)
}

function setScheduledAt(jobId: string, scheduledAt: Date): Promise<void> {
    return cyclotron.setScheduledAt(jobId, scheduledAt.toISOString())
}

function serializeObject(name: string, obj: Record<string, any> | null): string | null {
    if (obj === null) {
        return null
    } else if (typeof obj === 'object' && obj !== null) {
        return JSON.stringify(obj)
    }
    throw new Error(`${name} must be either an object or null`)
}

function setVmState(jobId: string, vmState: Record<string, any> | null): Promise<void> {
    const serialized = serializeObject('vmState', vmState)
    return cyclotron.setVmState(jobId, serialized)
}

function setMetadata(jobId: string, metadata: Record<string, any> | null): Promise<void> {
    const serialized = serializeObject('metadata', metadata)
    return cyclotron.setMetadata(jobId, serialized)
}

function setParameters(jobId: string, parameters: Record<string, any> | null): Promise<void> {
    const serialized = serializeObject('parameters', parameters)
    return cyclotron.setParameters(jobId, serialized)
}

function setBlob(jobId: string, blob: Uint8Array | null): Promise<void> {
    return cyclotron.setBlob(jobId, blob)
}

export default {
    initWorker,
    initManager,
    maybeInitWorker,
    maybeInitManager,
    createJob,
    dequeueJobs,
    dequeueJobsWithVmState,
    flushJob,
    setState,
    setQueue,
    setPriority,
    setScheduledAt,
    setVmState,
    setMetadata,
    setParameters,
    setBlob,
}
