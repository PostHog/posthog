import { Pool } from 'pg'
import { Redis } from 'ioredis'

export interface PluginsServerConfig {
    CELERY_DEFAULT_QUEUE: string
    DATABASE_URL: string
    PLUGINS_CELERY_QUEUE: string
    REDIS_URL: string
    BASE_DIR: string
}

export interface PluginsServer extends PluginsServerConfig {
    db: Pool,
    redis: Redis
}
