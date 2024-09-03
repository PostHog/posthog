export type PoolConfig = {
    dbUrl: string
    maxConnections?: number
    minConnections?: number
    acquireTimeoutSeconds?: number
    maxLifetimeSeconds?: number
    idleTimeoutSeconds?: number
}

// Type as expected by Cyclotron.
export type InternalPoolConfig = {
    db_url: string
    max_connections?: number
    min_connections?: number
    acquire_timeout_seconds?: number
    max_lifetime_seconds?: number
    idle_timeout_seconds?: number
}

export type JobState = 'available' | 'running' | 'completed' | 'failed' | 'paused'

export type Job = {
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
    vmState: object | null
    metadata: object | null
    parameters: object | null
    blob: Uint8Array | null
}

export type JobInit = Pick<Job, 'teamId' | 'functionId' | 'queueName' | 'priority'> &
    Pick<Partial<Job>, 'scheduled' | 'vmState' | 'parameters' | 'metadata' | 'blob'>

export type JobUpdate = Pick<Partial<Job>, 'queueName' | 'priority' | 'vmState' | 'parameters' | 'metadata' | 'blob'>
