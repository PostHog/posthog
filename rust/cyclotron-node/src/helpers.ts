import { CyclotronInternalPoolConfig, CyclotronPoolConfig } from './types'

export function convertToInternalPoolConfig(poolConfig: CyclotronPoolConfig): CyclotronInternalPoolConfig {
    return {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    }
}

export function serializeObject(name: string, obj: Record<string, any> | null): string | null {
    if (obj === null) {
        return null
    } else if (typeof obj === 'object' && obj !== null) {
        return JSON.stringify(obj)
    }
    throw new Error(`${name} must be either an object or null`)
}

export function deserializeObject(name: string, str: any): Record<string, any> | null {
    if (str === null) {
        return null
    } else if (typeof str === 'string') {
        return JSON.parse(str)
    }
    throw new Error(`${name} must be either a string or null`)
}
