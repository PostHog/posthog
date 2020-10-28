import { Pool } from 'pg'
import { Redis } from 'ioredis'
import { createVm } from './vm'
import { VM } from 'vm2'

export interface PluginsServerConfig {
    CELERY_DEFAULT_QUEUE: string
    DATABASE_URL: string
    PLUGINS_CELERY_QUEUE: string
    REDIS_URL: string
    BASE_DIR: string
    PLUGINS_RELOAD_PUBSUB_CHANNEL: string
}

export interface PluginsServer extends PluginsServerConfig {
    db: Pool
    redis: Redis
}

export interface Plugin {
    id: number
    name: string
    description: string
    url: string
    config_schema: Record<string, any>
    tag: string
    archive: Buffer | null
    from_json: boolean
    from_web: boolean
    error: any
}

export interface PluginConfig {
    id: number
    team_id: number
    plugin_id: number
    enabled: boolean
    order: number
    config: Record<string, any>
    error: any
}

export type VMMethod = 'processEvent' | 'setupTeam'

export interface PluginEvent extends Record<string, any>{

}

export interface PluginMeta extends Record<string, any>{

}

export interface PluginVM {
    plugin: Plugin
    indexJs: string | null
    libJs: string | null
    vm: VM,
    processEvent: (event: PluginEvent, meta: PluginMeta) => PluginEvent | null
    setupTeam: (meta: PluginMeta) => void
}
