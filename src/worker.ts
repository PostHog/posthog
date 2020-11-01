import { runPlugins } from './plugins'
import * as celery from 'celery-node'
import { PluginsServer } from './types'

export function startWorker(server: PluginsServer) {
    const worker = celery.createWorker(server.REDIS_URL, server.REDIS_URL, server.PLUGINS_CELERY_QUEUE)
    const client = celery.createClient(server.REDIS_URL, server.REDIS_URL, server.CELERY_DEFAULT_QUEUE)

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
            const processedEvent = await runPlugins(server, event)
            if (processedEvent) {
                const { distinct_id, ip, site_url, team_id, now, sent_at, ...data } = processedEvent
                client.sendTask('process_event', [], { distinct_id, ip, site_url, data, team_id, now, sent_at })
            }
        }
    )

    worker.register(
        'process_event_ee_with_plugins',
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
            const processedEvent = await runPlugins(server, event)
            if (processedEvent) {
                const { distinct_id, ip, site_url, team_id, now, sent_at, ...data } = processedEvent
                client.sendTask('process_event_ee', [], { distinct_id, ip, site_url, data, team_id, now, sent_at })
            }
        }
    )

    worker.start()
}