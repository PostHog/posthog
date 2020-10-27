const celery = require('celery-node')

const worker = celery.createWorker('redis://localhost/', 'redis://localhost/', 'posthog-plugins')
const client = celery.createClient('redis://localhost/', 'redis://localhost/', 'celery')

const processEvent = client.createTask('process_event')

worker.register(
    'process_event_with_plugins',
    (
        distinct_id: string,
        ip: string,
        site_url: string,
        data: Record<string, any>,
        team_id: number,
        now: string,
        sent_at?: string
    ) => {
        console.log(data)

        client.sendTask('process_event', [], { distinct_id, ip, site_url, data, team_id, now, sent_at })
    }
)
worker.start()
