import * as Sentry from '@sentry/node'
import { Kafka, Consumer, Message, EachBatchPayload } from 'kafkajs'
import { PluginsServer, Queue, RawEventMessage } from 'types'
import { KAFKA_EVENTS_WAL } from './topics'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { status } from '../status'

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

    private async eachBatch({
        batch,
        resolveOffset,
        heartbeat,
        commitOffsetsIfNecessary,
        uncommittedOffsets,
        isRunning,
        isStale,
    }: EachBatchPayload): Promise<void> {
        const batchProcessingTimer = new Date()
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
                status.info('😮', 'Consumer not running anymore, canceling batch processing!')
                return
            }
            if (isStale()) {
                status.info('😮', 'Batch stale, canceling batch processing!')
                return
            }
            const singleIngestionTimer = new Date()
            await this.saveEvent(event)
            resolveOffset(event.kafka_offset!)
            await heartbeat()
            await commitOffsetsIfNecessary()
            this.pluginsServer.statsd?.timing('kafka_queue.single_ingestion', singleIngestionTimer)
        }
        this.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchProcessingTimer)
    }

    async start(): Promise<void> {
        const startPromise = new Promise<void>(async (resolve, reject) => {
            this.consumer.on(this.consumer.events.GROUP_JOIN, () => resolve())
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true
            await this.consumer.subscribe({ topic: KAFKA_EVENTS_WAL })
            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                // TODO: eachBatchAutoResolve: false, // don't autoresolve whole batch in case we exit it early
                // The issue is right now we'd miss some messages and not resolve them as processEventBatch COMPETELY
                // discards some events, leaving us with no kafka_offset to resolve when in fact it should be resolved.
                autoCommitInterval: 500, // autocommit every 500 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                eachBatch: this.eachBatch,
            })
        })
        return await startPromise
    }

    async pause(): Promise<void> {
        if (!this.wasConsumerRan || this.isPaused()) {
            return
        }
        status.info('⏳', 'Pausing Kafka consumer...')
        await this.consumer.pause([{ topic: KAFKA_EVENTS_WAL }])
        status.info('⏸', 'Kafka consumer paused!')
    }

    async resume(): Promise<void> {
        if (!this.wasConsumerRan || !this.isPaused()) {
            return
        }
        status.info('⏳', 'Resuming Kafka consumer...')
        await this.consumer.resume([{ topic: KAFKA_EVENTS_WAL }])
        status.info('▶️', 'Kafka consumer resumed!')
    }

    isPaused(): boolean {
        return this.consumer.paused().some(({ topic }) => topic === KAFKA_EVENTS_WAL)
    }

    async stop(): Promise<void> {
        status.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer.stop()
            status.info('⏹', 'Kafka consumer stopped!')
        } catch (error) {
            status.error('⚠️', 'An error occurred while stopping Kafka queue:\n', error)
        }
        try {
            await this.consumer.disconnect()
        } catch {}
    }

    private static buildConsumer(kafka: Kafka): Consumer {
        const consumer = kafka.consumer({
            groupId: 'plugin-server',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            status.info('✅', `Kafka consumer joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            status.error('⚠️', `Kafka consumer group ${groupId} crashed:\n`, error)
            Sentry.captureException(error)
        })
        consumer.on(CONNECT, () => {
            status.info('✅', 'Kafka consumer connected!')
        })
        consumer.on(DISCONNECT, () => {
            status.info('🛑', 'Kafka consumer disconnected!')
        })
        return consumer
    }
}
