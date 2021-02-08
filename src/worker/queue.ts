import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import Client from '../celery/client'
import Worker from '../celery/worker'
import { KafkaQueue } from '../ingestion/kafka-queue'
import { status } from '../status'
import { PluginsServer, Queue } from '../types'
import { UUIDT } from '../utils'

export async function startQueue(
    server: PluginsServer,
    processEvent: (event: PluginEvent) => Promise<PluginEvent | null>,
    processEventBatch: (event: PluginEvent[]) => Promise<(PluginEvent | null)[]>
): Promise<Queue> {
    const relevantStartQueue = server.KAFKA_ENABLED ? startQueueKafka : startQueueRedis
    try {
        return await relevantStartQueue(server, processEvent, processEventBatch)
    } catch (error) {
        status.error('💥', 'Failed to start event queue:\n', error)
        throw error
    }
}

async function startQueueRedis(
    server: PluginsServer,
    processEvent: (event: PluginEvent) => Promise<PluginEvent | null>,
    processEventBatch: (event: PluginEvent[]) => Promise<(PluginEvent | null)[]>
): Promise<Queue> {
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
            try {
                const processedEvent = await processEvent(event)
                if (processedEvent) {
                    const { distinct_id, ip, site_url, team_id, now, sent_at, ...data } = processedEvent

                    if (server.PLUGIN_SERVER_INGESTION) {
                        await server.eventsProcessor.processEvent(
                            distinct_id,
                            ip,
                            site_url,
                            processedEvent,
                            team_id,
                            DateTime.fromISO(now),
                            sent_at ? DateTime.fromISO(sent_at) : null,
                            new UUIDT().toString()
                        )
                    } else {
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
            } catch (e) {
                Sentry.captureException(e)
            }
        }
    )

    worker.start()

    return worker
}

async function startQueueKafka(
    server: PluginsServer,
    processEvent: (event: PluginEvent) => Promise<PluginEvent | null>,
    processEventBatch: (event: PluginEvent[]) => Promise<(PluginEvent | null)[]>
): Promise<Queue> {
    const kafkaQueue = new KafkaQueue(server, processEventBatch, async (event: PluginEvent) => {
        const { distinct_id, ip, site_url, team_id, now, sent_at, uuid } = event
        if (!uuid) {
            status.error('❓', 'UUID missing in event received from Kafka!')
            return
        }
        if (server.PLUGIN_SERVER_INGESTION) {
            await server.eventsProcessor.processEvent(
                distinct_id,
                ip,
                site_url,
                event,
                team_id,
                DateTime.fromISO(now),
                sent_at ? DateTime.fromISO(sent_at) : null,
                uuid
            )
        }
    })

    await kafkaQueue.start()

    return kafkaQueue
}
