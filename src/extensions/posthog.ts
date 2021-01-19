import { KAFKA_EVENTS_WAL } from '../ingestion/topics'
import { DateTime } from 'luxon'
import { PluginsServer, PluginConfig, RawEventMessage } from 'types'
import { version } from '../../package.json'
import Client from '../celery/client'
import { UUIDT } from '../utils'

export interface DummyPostHog {
    capture(event: string, properties?: Record<string, any>): void
}

export function createPosthog(server: PluginsServer, pluginConfig: PluginConfig): DummyPostHog {
    const distinctId = pluginConfig.plugin?.name || `plugin-id-${pluginConfig.plugin_id}`

    const client = server.KAFKA_ENABLED ? null : new Client(server.redis, server.PLUGINS_CELERY_QUEUE) // Redis
    const producer = server.KAFKA_ENABLED ? server.kafka!.producer() : null // Kafka
    producer?.connect()

    function sendEventRedis(event: string, properties: Record<string, any>, timestamp: string) {
        const data = {
            distinct_id: distinctId,
            event,
            timestamp,
            properties: {
                $lib: 'posthog-plugin-server',
                $lib_version: version,
                ...properties,
            },
        }

        client!.sendTask(
            'posthog.tasks.process_event.process_event_with_plugins',
            [distinctId, null, null, data, pluginConfig.team_id, timestamp, timestamp],
            {}
        )
    }

    function sendEventKafka(event: string, properties: Record<string, any>, timestamp: string) {
        const uuid = new UUIDT().toString()
        const data = {
            distinct_id: distinctId,
            event,
            timestamp,
            properties: {
                $lib: 'posthog-plugin-server',
                $lib_version: version,
                ...properties,
            },
        }

        producer!.send({
            topic: KAFKA_EVENTS_WAL,
            messages: [
                {
                    key: uuid,
                    value: JSON.stringify({
                        distinct_id: distinctId,
                        ip: '',
                        site_url: '',
                        data: JSON.stringify(data),
                        team_id: pluginConfig.team_id,
                        now: timestamp,
                        sent_at: timestamp,
                        uuid,
                    } as RawEventMessage),
                },
            ],
        })
    }

    const sendEvent = server.KAFKA_ENABLED ? sendEventKafka : sendEventRedis

    return {
        capture(event, properties = {}) {
            const { timestamp, ...otherProperties } = properties
            sendEvent(event, otherProperties, timestamp || DateTime.utc().toISO())
        },
    }
}
