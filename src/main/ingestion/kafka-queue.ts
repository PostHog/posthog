import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, EachMessagePayload, Kafka, KafkaMessage } from 'kafkajs'
import { PluginsServer, Queue } from 'types'

import { timeoutGuard } from '../../shared/ingestion/utils'
import { status } from '../../shared/status'
import { groupIntoBatches, killGracefully, sanitizeEvent } from '../../shared/utils'

export class KafkaQueue implements Queue {
    private pluginsServer: PluginsServer
    private piscina: Piscina
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private processEvent: (event: PluginEvent) => Promise<PluginEvent>
    private ingestEvent: (event: PluginEvent) => Promise<void>

    // used for logging aggregate stats to the console
    private messageLogDate = 0
    private messageCounter = 0

    constructor(
        pluginsServer: PluginsServer,
        piscina: Piscina,
        processEvent: (event: PluginEvent) => Promise<any>,
        ingestEvent: (event: PluginEvent) => Promise<void>
    ) {
        this.pluginsServer = pluginsServer
        this.piscina = piscina
        this.kafka = pluginsServer.kafka!
        this.consumer = KafkaQueue.buildConsumer(this.kafka)
        this.wasConsumerRan = false
        this.processEvent = processEvent
        this.ingestEvent = ingestEvent
        this.messageLogDate = new Date().valueOf()
    }

    private async eachMessage(message: KafkaMessage): Promise<void> {
        const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
        const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
        const event: PluginEvent = sanitizeEvent({
            ...combinedEvent,
            site_url: combinedEvent.site_url || null,
            ip: combinedEvent.ip || null,
        })
        await this.eachEvent(event)
    }

    private async eachEvent(event: PluginEvent): Promise<void> {
        const eachEventStartTimer = new Date()

        const processingTimeout = timeoutGuard('Still running plugins on event. Timeout warning after 30 sec!', {
            event: JSON.stringify(event),
        })
        const timer = new Date()
        let processedEvent: PluginEvent
        try {
            processedEvent = await this.processEvent(event)
        } catch (error) {
            status.info('🔔', error)
            Sentry.captureException(error)
            throw error
        } finally {
            this.pluginsServer.statsd?.timing('kafka_queue.single_event', timer)
            clearTimeout(processingTimeout)
        }

        // ingest event

        if (processedEvent) {
            const singleIngestionTimeout = timeoutGuard('After 30 seconds still ingesting event', {
                event: JSON.stringify(processedEvent),
            })
            const singleIngestionTimer = new Date()
            try {
                await this.ingestEvent(processedEvent)
            } catch (error) {
                status.info('🔔', error)
                Sentry.captureException(error)
                throw error
            } finally {
                this.pluginsServer.statsd?.timing('kafka_queue.single_ingestion', singleIngestionTimer)
                clearTimeout(singleIngestionTimeout)
            }
        }

        this.pluginsServer.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)

        this.countAndLogEvents()
    }

    private async eachBatch({
        batch,
        resolveOffset,
        heartbeat,
        commitOffsetsIfNecessary,
        isRunning,
        isStale,
    }: EachBatchPayload): Promise<void> {
        const batchStartTimer = new Date()

        try {
            const messageBatches = groupIntoBatches(
                batch.messages,
                this.pluginsServer.WORKER_CONCURRENCY * this.pluginsServer.TASKS_PER_WORKER
            )

            for (const messageBatch of messageBatches) {
                if (!isRunning() || isStale()) {
                    status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events`, {
                        isRunning: isRunning(),
                        isStale: isStale(),
                        msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                    })
                    return
                }

                await Promise.all(messageBatch.map((message) => this.eachMessage(message)))

                // this if should never be false, but who can trust computers these days
                if (messageBatch.length > 0) {
                    resolveOffset(messageBatch[messageBatch.length - 1].offset)
                }
                await commitOffsetsIfNecessary()
                await heartbeat()
            }

            status.info(
                '🧩',
                `Kafka batch of ${batch.messages.length} events completed in ${
                    new Date().valueOf() - batchStartTimer.valueOf()
                }ms`
            )
        } finally {
            this.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchStartTimer)
        }
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
                eachBatchAutoResolve: false,
                autoCommitInterval: 1000, // autocommit every 1000 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                eachBatch: async (payload) => {
                    try {
                        await this.eachBatch(payload)
                    } catch (error) {
                        status.info('💀', `Kafka batch of ${payload.batch.messages.length} events failed!`)
                        if (error.type === 'UNKNOWN_MEMBER_ID') {
                            status.info(
                                '💀',
                                "Probably the batch took longer than the session and we couldn't commit the offset"
                            )
                        }
                        Sentry.captureException(error)
                        throw error
                    }
                },
            })
        })
        return await startPromise
    }

    async pause(): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused()) {
            status.info('⏳', 'Pausing Kafka consumer...')
            this.consumer.pause([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('⏸', 'Kafka consumer paused!')
        }
        return Promise.resolve()
    }

    resume(): void {
        if (this.wasConsumerRan && this.isPaused()) {
            status.info('⏳', 'Resuming Kafka consumer...')
            this.consumer.resume([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('▶️', 'Kafka consumer resumed!')
        }
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

    private countAndLogEvents() {
        const now = new Date().valueOf()
        this.messageCounter++
        if (now - this.messageLogDate > 10000) {
            status.info(
                '🕒',
                `Processed ${this.messageCounter} events in ${Math.round((now - this.messageLogDate) / 10) / 100}s`
            )
            this.messageCounter = 0
            this.messageLogDate = now
        }
    }
}
