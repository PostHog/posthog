import { runPlugins } from './plugins'
import { PluginsServer } from './types'
import { PluginEvent } from 'posthog-plugins'

import Worker from './celery/worker'
import Client from './celery/client'

export function startWorker(server: PluginsServer): () => Promise<void> {
    const worker = new Worker(server.redis, server.PLUGINS_CELERY_QUEUE)
    const client = new Client(server.redis, server.CELERY_DEFAULT_QUEUE)

    worker.register(
        'posthog.tasks.process_event.process_event_with_plugins',
        async (
            distinct_id: string,
            ip: string,
            site_url: string,
            data: Record<string, unknown>,
            team_id: number,
            now: string,
            sent_at?: string
        ) => {
            const event = { distinct_id, ip, site_url, team_id, now, sent_at, ...data } as PluginEvent
            const processedEvent = await runPlugins(server, event)
            if (processedEvent) {
                const { distinct_id, ip, site_url, team_id, now, sent_at, ...data } = processedEvent
                client.sendTask('posthog.tasks.process_event.process_event', [], {
                    distinct_id,
                    ip,
                    site_url,
                    data,
                    team_id,
                    now,
                    sent_at,
                })
            }
        }
    )

    worker.start()

    return async () => worker.stop()
}
