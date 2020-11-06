import { Pool } from 'pg'
import { Redis } from 'ioredis'
import { PluginEvent, PluginMeta } from 'posthog-plugins'
import { VMScript } from 'vm2'

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
    config_schema: Record<string, PluginConfigSchema>
    tag: string
    archive: Buffer | null
    from_json: boolean
    from_web: boolean
    error?: PluginError
}

export interface PluginConfig {
    id: number
    team_id: number
    plugin_id: number
    enabled: boolean
    order: number
    config: Record<string, unknown>
    error?: PluginError
}

export interface PluginJsonConfig {
    name?: string
    description?: string
    url?: string
    main?: string
    lib?: string
    config?: Record<string, PluginConfigSchema>
}

export interface PluginConfigSchema {
    name: string
    type: 'string' | 'file'
    default: string
    required: boolean
}

export interface PluginError {
    message: string
    time: string
    name?: string
    stack?: string
    event?: PluginEvent | null
}

export interface PluginAttachment {
    id: number
    team_id: number
    plugin_config_id: number
    key: string
    content_type: string
    file_name: string
    contents: Buffer | null
}

export interface MetaAttachment {
    content_type: string
    file_name: string
    contents: Buffer | null
}

export type VMMethod = 'processEvent' | 'setupTeam'

export interface PluginScript {
    plugin: Plugin
    script: VMScript
    processEvent: boolean
    setupTeam: boolean
}

export interface PluginScriptMethods {
    processEvent: (event: PluginEvent, meta: PluginMeta) => PluginEvent | null
    setupTeam: (meta: PluginMeta) => void
}
