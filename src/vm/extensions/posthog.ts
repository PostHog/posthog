import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { PluginConfig, PluginsServer, RawEventMessage } from 'types'

import Client from '../../celery/client'
import { UUIDT } from '../../utils'

const { version } = require('../../../package.json')

interface InternalData {
    distinct_id: string
    event: string
    timestamp: string
    properties: Properties
    team_id: number
    uuid: string
}

export interface DummyPostHog {
    capture(event: string, properties?: Record<string, any>): void
}

export function createPosthog(server: PluginsServer, pluginConfig: PluginConfig): DummyPostHog {
    const distinctId = pluginConfig.plugin?.name || `plugin-id-${pluginConfig.plugin_id}`

    let sendEvent: (data: InternalData) => void

    if (server.KAFKA_ENABLED) {
        // Sending event to our Kafka>ClickHouse pipeline
        sendEvent = (data) => {
            if (!server.kafkaProducer) {
                throw new Error('kafkaProducer not configured!')
            }
            // ignore the promise, run in the background just like with celery
            void server.db.queueKafkaMessage({
                topic: server.KAFKA_CONSUMPTION_TOPIC!,
                messages: [
                    {
                        key: data.uuid,
                        value: JSON.stringify({
                            distinct_id: data.distinct_id,
                            ip: '',
                            site_url: '',
                            data: JSON.stringify(data),
                            team_id: pluginConfig.team_id,
                            now: data.timestamp,
                            sent_at: data.timestamp,
                            uuid: data.uuid,
                        } as RawEventMessage),
                    },
                ],
            })
        }
    } else {
        // Sending event to our Redis>Postgres pipeline
        const client = new Client(server.db, server.PLUGINS_CELERY_QUEUE)
        sendEvent = (data) => {
            client.sendTask(
                'posthog.tasks.process_event.process_event_with_plugins',
                [data.distinct_id, null, null, data, pluginConfig.team_id, data.timestamp, data.timestamp],
                {}
            )
        }
    }

    return {
        capture(event, properties = {}) {
            const { timestamp = DateTime.utc().toISO(), distinct_id = distinctId, ...otherProperties } = properties
            const data: InternalData = {
                distinct_id,
                event,
                timestamp,
                properties: {
                    $lib: 'posthog-plugin-server',
                    $lib_version: version,
                    distinct_id,
                    ...otherProperties,
                },
                team_id: pluginConfig.team_id,
                uuid: new UUIDT().toString(),
            }
            sendEvent(data)
        },
    }
}
