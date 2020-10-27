import { runPlugins } from './plugins'
import * as celery from 'celery-node'
import { PluginsServerConfig } from './types'

export function startWorker(config: PluginsServerConfig) {
    const worker = celery.createWorker(config.REDIS_URL, config.REDIS_URL, config.PLUGINS_CELERY_QUEUE)
    const client = celery.createClient(config.REDIS_URL, config.REDIS_URL, config.CELERY_DEFAULT_QUEUE)

    worker.register(
        'process_event_with_plugins',
        async (
            distinct_id: string,
            ip: string,
            site_url: string,
            data: Record<string, any>,
            team_id: number,
            now: string,
            sent_at?: string
        ) => {
            const event = { distinct_id, ip, site_url, team_id, now, sent_at, ...data }
            const processedEvent = await runPlugins(event)
            if (processedEvent) {
                const { distinct_id, ip, site_url, team_id, now, sent_at, ...data } = processedEvent
                client.sendTask('process_event', [], { distinct_id, ip, site_url, data, team_id, now, sent_at })
            }
        }
    )

    worker.start()
}