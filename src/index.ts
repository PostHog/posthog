import { runPlugins, setupPlugins } from './plugins'
import * as celery from 'celery-node'

const worker = celery.createWorker('redis://localhost/', 'redis://localhost/', 'posthog-plugins')
const client = celery.createClient('redis://localhost/', 'redis://localhost/', 'celery')

const processEvent = client.createTask('process_event')

setupPlugins()

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
