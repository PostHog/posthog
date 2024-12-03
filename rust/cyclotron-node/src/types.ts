export type CyclotronPoolConfig = {
    dbUrl: string
    maxConnections?: number
    minConnections?: number
    acquireTimeoutSeconds?: number
    maxLifetimeSeconds?: number
    idleTimeoutSeconds?: number
}

// Type as expected by Cyclotron.
export type CyclotronInternalPoolConfig = {
    db_url: string
    max_connections?: number
    min_connections?: number
    acquire_timeout_seconds?: number
    max_lifetime_seconds?: number
    idle_timeout_seconds?: number
}

// Config specific to tuning the worker batch flush and heartbeat behaviour
export type CyclotronWorkerTuningConfig = {
    // The worker will issue at most 1 heartbeat per this many seconds per job.
    heartbeatWindowSeconds?: number
    // Updates released by the worker will be buffered for at most this many milliseconds before a flush is attempted.
    lingerTimeMs?: number
    // The maximum number of updates that can be buffered before a flush is attempted.
    maxUpdatesBuffered?: number
    // The maximum number of update bytes the worker will buffer, calculated as the sum of VM state and blob
    maxBytesBuffered?: number
    // The worker flushes update batches in a background loop, which will check if a flush is due based on the
    // conditions above every this many milliseconds. Users may also call forceFlush(), which will try to flush any
    // pending updates immediately.
    flushLoopIntervalMs?: number
}

export type CyclotronJobState = 'available' | 'running' | 'completed' | 'failed' | 'paused'

export type CyclotronJob = {
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
    state: CyclotronJobState
    priority: number
    scheduled: Date
    vmState: object | null
    metadata: object | null
    parameters: object | null
    blob: Uint8Array | null
}

export type CyclotronJobInit = Pick<CyclotronJob, 'teamId' | 'functionId' | 'queueName' | 'priority'> &
    Pick<Partial<CyclotronJob>, 'scheduled' | 'vmState' | 'parameters' | 'metadata' | 'blob'>

export type CyclotronJobUpdate = Pick<
    Partial<CyclotronJob>,
    'queueName' | 'priority' | 'vmState' | 'parameters' | 'metadata' | 'blob'
>
