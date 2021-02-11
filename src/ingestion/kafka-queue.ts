import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, Kafka, Message } from 'kafkajs'
import { PluginsServer, Queue, RawEventMessage } from 'types'

import { status } from '../status'
import { killGracefully, runInParallelBatches } from '../utils'

export class KafkaQueue implements Queue {
    private pluginsServer: PluginsServer
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private processEventBatch: (batch: PluginEvent[]) => Promise<PluginEvent[]>
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
        isRunning,
        isStale,
    }: EachBatchPayload): Promise<void> {
        const batchProcessingTimer = new Date()

        const uuidOrder = new Map<string, number>()
        const uuidOffset = new Map<string, string>()
        const pluginEvents: PluginEvent[] = batch.messages.map((message, index) => {
            const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
            const event = { ...rawEvent, ...JSON.parse(dataStr) }
            uuidOrder.set(event.uuid, index)
            uuidOffset.set(event.uuid, message.offset)
            return {
                ...event,
                site_url: event.site_url || null,
                ip: event.ip || null,
            }
        })

        const maxBatchSize = Math.max(
            1,
            Math.min(
                100,
                Math.ceil(
                    pluginEvents.length / this.pluginsServer.WORKER_CONCURRENCY / this.pluginsServer.TASKS_PER_WORKER
                )
            )
        )
        const processedEvents = await runInParallelBatches(pluginEvents, maxBatchSize, this.processEventBatch)

        // Sort in the original order that the events came in, putting any randomly added events to the end.
        // This is so we would resolve the correct kafka offsets in order.
        processedEvents.sort(
            (a, b) => (uuidOrder.get(a.uuid!) || pluginEvents.length) - (uuidOrder.get(b.uuid!) || pluginEvents.length)
        )

        // TODO: add chunking into groups of 500 or so. Might start too many promises at once now
        if (this.pluginsServer.KAFKA_BATCH_PARALELL_PROCESSING) {
            const ingestOneEvent = async (event: PluginEvent) => {
                const singleIngestionTimer = new Date()
                await this.saveEvent(event)
                this.pluginsServer.statsd?.timing('kafka_queue.single_ingestion', singleIngestionTimer)
            }
            await Promise.all(processedEvents.map((event) => ingestOneEvent(event)))
        } else {
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
                const offset = uuidOffset.get(event.uuid!)
                if (offset) {
                    resolveOffset(offset)
                }
                await heartbeat()
                await commitOffsetsIfNecessary()
                this.pluginsServer.statsd?.timing('kafka_queue.single_ingestion', singleIngestionTimer)
            }
        }
        this.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchProcessingTimer)
        resolveOffset(batch.lastOffset())
        await heartbeat()
        await commitOffsetsIfNecessary()
    }

    async start(): Promise<void> {
        const startPromise = new Promise<void>(async (resolve, reject) => {
            this.consumer.on(this.consumer.events.GROUP_JOIN, () => resolve())
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true
            await this.consumer.subscribe({ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! })
            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                eachBatchAutoResolve: false, // we are resolving the last offset of the batch more deliberately
                autoCommitInterval: 500, // autocommit every 500 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                eachBatch: async (payload) => {
                    try {
                        await this.eachBatch(payload)
                    } catch (error) {
                        Sentry.captureException(error)
                        throw error
                    }
                },
            })
        })
        return await startPromise
    }

    async pause(): Promise<void> {
        if (!this.wasConsumerRan || this.isPaused()) {
            return
        }
        status.info('⏳', 'Pausing Kafka consumer...')
        await this.consumer.pause([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
        status.info('⏸', 'Kafka consumer paused!')
    }

    async resume(): Promise<void> {
        if (!this.wasConsumerRan || !this.isPaused()) {
            return
        }
        status.info('⏳', 'Resuming Kafka consumer...')
        await this.consumer.resume([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
        status.info('▶️', 'Kafka consumer resumed!')
    }

    isPaused(): boolean {
        return this.consumer.paused().some(({ topic }) => topic === this.pluginsServer.KAFKA_CONSUMPTION_TOPIC)
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
            groupId: 'clickhouse-ingestion',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            status.info('✅', `Kafka consumer joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            status.error('⚠️', `Kafka consumer group ${groupId} crashed:\n`, error)
            Sentry.captureException(error)
            killGracefully()
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
