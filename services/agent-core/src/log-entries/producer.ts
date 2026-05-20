import { HighLevelProducer, type ProducerGlobalConfig } from 'node-rdkafka'
/**
 * Kafka producer for agent log entries.
 *
 * Uses `node-rdkafka` (same as the rest of the repo). librdkafka handles
 * batching natively via `linger.ms` + `batch.size`, so there is no
 * in-process buffer here — `append` calls go straight to
 * `producer.produce()` and rdkafka coalesces them on the wire.
 *
 * **Per-topic config**, deliberately. Each `KafkaLogProducer` is
 * constructed with its own brokers / overrides; we do NOT share a single
 * client across topics. When app_metrics2 lands it'll be a sibling
 * producer with its own settings, not a registry lookup.
 */
import { hostname } from 'node:os'

import { logger } from '../logger'
import { safeClickhouseString } from './safe-clickhouse-string'
import type { LogEntry } from './types'

export interface KafkaLogProducerOptions {
    /** Comma-separated brokers, e.g. `kafka:9092`. */
    brokers: string
    /** Defaults to `log_entries` (matches CDP's topic). */
    topic?: string
    /** Optional rdkafka overrides; merged over the defaults below. */
    config?: Partial<ProducerGlobalConfig>
    /** Optional name for log lines / future metrics labels. Defaults to topic. */
    name?: string
}

/** Sensible defaults for a low-volume, fire-and-forget producer. */
const DEFAULT_CONFIG: ProducerGlobalConfig = {
    'client.id': hostname(),
    // librdkafka handles batching for us; we just need to set linger so
    // small bursts of log lines pack into one Kafka message.
    'linger.ms': 20,
    'batch.size': 8 * 1024 * 1024,
    'queue.buffering.max.messages': 100_000,
    'compression.codec': 'snappy',
    'metadata.max.age.ms': 30_000,
    'socket.timeout.ms': 30_000,
}

export interface LogProducer {
    /** Connect to the broker. Call once at startup. */
    connect(): Promise<void>
    /** Fire-and-forget. Drops the entry if not connected yet (logged). */
    append(entry: LogEntry): void
    /** Flush pending + disconnect. Call once at shutdown. */
    disconnect(): Promise<void>
}

export class KafkaLogProducer implements LogProducer {
    private readonly producer: HighLevelProducer
    private readonly topic: string
    private readonly name: string
    private connected = false
    private connectPromise: Promise<void> | null = null
    private disposed = false

    constructor(opts: KafkaLogProducerOptions) {
        this.topic = opts.topic ?? 'log_entries'
        this.name = opts.name ?? this.topic
        const merged: ProducerGlobalConfig = {
            ...DEFAULT_CONFIG,
            'metadata.broker.list': opts.brokers,
            ...opts.config,
            dr_cb: false,
        }
        this.producer = new HighLevelProducer(merged)
        this.producer.on('event.error', (err) =>
            logger.error('kafka log producer: rdkafka error', { name: this.name, error: String(err) })
        )
    }

    connect(): Promise<void> {
        if (this.connected) {
            return Promise.resolve()
        }
        if (!this.connectPromise) {
            this.connectPromise = new Promise<void>((resolve, reject) => {
                this.producer.connect(undefined, (err, data) => {
                    if (err) {
                        this.connectPromise = null
                        reject(err)
                        return
                    }
                    this.connected = true
                    logger.info('kafka log producer connected', {
                        name: this.name,
                        topic: this.topic,
                        brokers: data?.brokers,
                    })
                    resolve()
                })
            })
        }
        return this.connectPromise
    }

    append(entry: LogEntry): void {
        if (this.disposed) {
            return
        }
        if (!this.connected) {
            logger.warn('kafka log producer: dropping entry (not connected)', {
                name: this.name,
                topic: this.topic,
            })
            return
        }
        const value = Buffer.from(safeClickhouseString(JSON.stringify(entry)))
        try {
            // Fire-and-forget. HighLevelProducer requires a delivery callback;
            // we don't await it — librdkafka enqueues + retries internally,
            // and broker-level errors surface via the `event.error` handler.
            // For our volume (a few hundred entries/session), the in-memory
            // pending-ack overhead is negligible.
            this.producer.produce(this.topic, null, value, null, Date.now(), noopDeliveryCallback)
        } catch (err) {
            logger.error('kafka log producer: produce failed', {
                name: this.name,
                topic: this.topic,
                error: String(err),
            })
        }
    }

    async disconnect(): Promise<void> {
        this.disposed = true
        if (!this.connected) {
            return
        }
        await new Promise<void>((resolve) =>
            this.producer.flush(5_000, () => {
                resolve()
            })
        )
        await new Promise<void>((resolve) =>
            this.producer.disconnect(() => {
                resolve()
            })
        )
        this.connected = false
    }
}

/** HighLevelProducer's `produce` requires a delivery callback; we ignore it. */
function noopDeliveryCallback(): void {
    /* intentionally empty */
}

/** In-memory producer for tests. Records every entry it would have produced. */
export class FakeLogProducer implements LogProducer {
    readonly entries: LogEntry[] = []

    async connect(): Promise<void> {
        // no-op
    }

    append(entry: LogEntry): void {
        this.entries.push(entry)
    }

    async disconnect(): Promise<void> {
        // no-op
    }
}
