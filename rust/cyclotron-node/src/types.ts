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
    scheduled: string | null
    vmState: object | null
    metadata: object | null
    parameters: object | null
    blob: Uint8Array | null
}

export type CyclotronJobInit = Pick<CyclotronJob, 'id'| 'teamId' | 'functionId' | 'queueName' | 'priority'> &
        Pick<Partial<CyclotronJob>, 'scheduled' | 'vmState' | 'parameters' | 'metadata' | 'blob'>

export type CyclotronJobUpdate = Pick<
    Partial<CyclotronJob>,
    'queueName' | 'priority' | 'vmState' | 'parameters' | 'metadata' | 'blob' | 'scheduled'
>
