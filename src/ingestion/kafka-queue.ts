import * as Sentry from '@sentry/node'
import { Kafka, Consumer, Message } from 'kafkajs'
import { ParsedEventMessage, PluginsServer, Queue, RawEventMessage } from 'types'
import { KAFKA_EVENTS_WAL } from './topics'
import { version } from '../../package.json'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

export type BatchCallback = (messages: Message[]) => Promise<void>

export class KafkaQueue implements Queue {
    private pluginsServer: PluginsServer
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private processEventBatch: (batch: PluginEvent[]) => Promise<any>
    private saveEvent: (event: PluginEvent) => Promise<void>

    constructor(
        pluginsServer: PluginsServer,
        processEventBatch: (batch: PluginEvent[]) => Promise<any>,
        saveEvent: (event: PluginEvent) => Promise<void>
    ) {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.consumer = KafkaQueue.buildConsumer(this.kafka)
        this.wasConsumerRan = false
        this.processEventBatch = processEventBatch
        this.saveEvent = saveEvent
    }

    async start(): Promise<void> {
        console.info(`⏬ Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
        await this.consumer.subscribe({ topic: KAFKA_EVENTS_WAL })
        // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
        await this.consumer.run({
            // TODO: eachBatchAutoResolve: false, // don't autoresolve whole batch in case we exit it early
            // The issue is right now we'd miss some messages and not resolve them as processEventBatch COMPETELY
            // discards some events, leaving us with no kafka_offset to resolve when in fact it should be resolved.
            autoCommitInterval: 500, // autocommit every 500 ms…
            autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
            eachBatch: async ({
                batch,
                resolveOffset,
                heartbeat,
                commitOffsetsIfNecessary,
                uncommittedOffsets,
                isRunning,
                isStale,
            }) => {
                const rawEvents: RawEventMessage[] = batch.messages.map((message) => ({
                    ...JSON.parse(message.value!.toString()),
                    kafka_offset: message.offset,
                }))
                const parsedEvents = rawEvents.map((rawEvent) => ({
                    ...rawEvent,
                    data: JSON.parse(rawEvent.data),
                }))
                const pluginEvents: PluginEvent[] = parsedEvents.map((parsedEvent) => ({
                    ...parsedEvent,
                    event: parsedEvent.data.event,
                    properties: parsedEvent.data.properties,
                }))
                const processedEvents: PluginEvent[] = (
                    await this.processEventBatch(pluginEvents)
                ).filter((event: PluginEvent[] | false | null | undefined) => Boolean(event))
                for (const event of processedEvents) {
                    if (!isRunning()) {
                        console.info('😮 Consumer not running anymore, canceling batch processing!')
                        return
                    }
                    if (isStale()) {
                        console.info('😮 Batch stale, canceling batch processing!')
                        return
                    }
                    await this.saveEvent(event)
                    resolveOffset(event.kafka_offset!)
                    await heartbeat()
                    await commitOffsetsIfNecessary()
                }
            },
        })
        this.wasConsumerRan = true
    }

    async pause(): Promise<void> {
        if (!this.wasConsumerRan || this.isPaused()) {
            return
        }
        console.error('⏳ Pausing Kafka consumer...')
        await this.consumer.pause([{ topic: KAFKA_EVENTS_WAL }])
        console.error('⏸ Kafka consumer paused!')
    }

    async resume(): Promise<void> {
        if (!this.wasConsumerRan || !this.isPaused()) {
            return
        }
        console.error('⏳ Resuming Kafka consumer...')
        await this.consumer.resume([{ topic: KAFKA_EVENTS_WAL }])
        console.error('▶️ Kafka consumer resumed!')
    }

    isPaused(): boolean {
        return this.consumer.paused().some(({ topic }) => topic === KAFKA_EVENTS_WAL)
    }

    async stop(): Promise<void> {
        console.info(`⏳ Stopping Kafka queue...`)
        await this.consumer.stop()
        console.error('⏹ Kafka consumer stopped!')
        await this.consumer.disconnect()
    }

    private static buildConsumer(kafka: Kafka): Consumer {
        const consumer = kafka.consumer({
            groupId: 'plugin-server',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            console.info(`✅ Kafka consumer joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            console.error(`⚠️ Kafka consumer group ${groupId} crashed!`)
            console.error(error)
            Sentry.captureException(error)
        })
        consumer.on(CONNECT, () => {
            console.info(`✅ Kafka consumer connected!`)
        })
        consumer.on(DISCONNECT, () => {
            console.info(`🛑 Kafka consumer disconnected!`)
        })
        return consumer
    }
}
