export interface PluginsServerConfig {
    CELERY_DEFAULT_QUEUE: string
    DATABASE_URL: string
    PLUGINS_CELERY_QUEUE: string
    REDIS_URL: string
    BASE_DIR: string
}
