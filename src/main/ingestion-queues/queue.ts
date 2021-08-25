import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { CeleryTriggeredJobOperation, Hub, PluginConfig, Queue, Team, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { sanitizeEvent, UUIDT } from '../../utils/utils'
import { CeleryQueue } from './celery-queue'
import { ingestEvent } from './ingest-event'
import { KafkaQueue } from './kafka-queue'

interface Queues {
    ingestion: Queue
    auxiliary: Queue
}

export function pauseQueueIfWorkerFull(
    pause: undefined | (() => void | Promise<void>),
    server: Hub,
    piscina?: Piscina
): void {
    if (pause && (piscina?.queueSize || 0) > (server.WORKER_CONCURRENCY || 4) * (server.WORKER_CONCURRENCY || 4)) {
        void pause()
    }
}

export async function startQueues(
    server: Hub,
    piscina: Piscina,
    workerMethods: Partial<WorkerMethods> = {}
): Promise<Queues> {
    const mergedWorkerMethods = {
        onEvent: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'onEvent'
            return piscina.run({ task: 'onEvent', args: { event } })
        },
        onSnapshot: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'onSnapshot'
            return piscina.run({ task: 'onSnapshot', args: { event } })
        },
        processEvent: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'processEvent'
            return piscina.run({ task: 'processEvent', args: { event } })
        },
        ingestEvent: (event: PluginEvent) => {
            server.lastActivity = new Date().valueOf()
            server.lastActivityType = 'ingestEvent'
            return piscina.run({ task: 'ingestEvent', args: { event } })
        },
        ...workerMethods,
    }

    try {
        const redisQueue = startQueueRedis(server, piscina, mergedWorkerMethods)
        const queues = {
            ingestion: redisQueue,
            auxiliary: redisQueue,
        }
        if (server.KAFKA_ENABLED) {
            queues.ingestion = await startQueueKafka(server, piscina, mergedWorkerMethods)
        }
        return queues
    } catch (error) {
        status.error('💥', 'Failed to start event queue:\n', error)
        throw error
    }
}

function startQueueRedis(server: Hub, piscina: Piscina, workerMethods: WorkerMethods): Queue {
    const celeryQueue = new CeleryQueue(server.db, server.PLUGINS_CELERY_QUEUE)

    // this queue is for triggering plugin jobs from the PostHog UI
    celeryQueue.register(
        'posthog.tasks.plugins.plugin_job',
        async (
            pluginConfigTeam: Team['id'],
            pluginConfigId: PluginConfig['id'],
            type: string,
            jobOp: CeleryTriggeredJobOperation,
            payload: Record<string, any>
        ) => {
            try {
                payload['$operation'] = jobOp
                const job = {
                    type,
                    payload,
                    pluginConfigId,
                    pluginConfigTeam,
                    timestamp: Date.now(),
                }
                pauseQueueIfWorkerFull(() => celeryQueue.pause(), server, piscina)
                await piscina?.run({ task: 'enqueueJob', args: { job } })
            } catch (e) {
                Sentry.captureException(e)
            }
        }
    )

    // if kafka is enabled, we'll process events from there
    if (!server.KAFKA_ENABLED) {
        celeryQueue.register(
            'posthog.tasks.process_event.process_event_with_plugins',
            async (
                distinct_id: string,
                ip: string | null,
                site_url: string,
                data: Record<string, unknown>,
                team_id: number,
                now: string,
                sent_at?: string
            ) => {
                const event = sanitizeEvent({
                    distinct_id,
                    ip,
                    site_url,
                    team_id,
                    now,
                    sent_at,
                    uuid: new UUIDT().toString(),
                    ...data,
                } as PluginEvent)
                try {
                    const checkAndPause = () => pauseQueueIfWorkerFull(() => celeryQueue.pause(), server, piscina)
                    await ingestEvent(server, workerMethods, event, checkAndPause)
                } catch (e) {
                    Sentry.captureException(e)
                }
            }
        )
    }

    // run in the background
    void celeryQueue.start()

    return celeryQueue
}

async function startQueueKafka(server: Hub, piscina: Piscina, workerMethods: WorkerMethods): Promise<Queue> {
    const kafkaQueue: Queue = new KafkaQueue(server, piscina, workerMethods)
    await kafkaQueue.start()

    return kafkaQueue
}
