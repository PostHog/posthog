/**
 * AnalyticsSink — the runner's LLM-analytics out-bound. One `$ai_generation`
 * per pi-ai call, one `$ai_span` per tool dispatch, written to a dedicated
 * Kafka topic the agent platform owns:
 *
 *   runner ─Kafka─▶ topic: agent_ai_events ─consumer─▶ (future) clickhouse_ai_events_json (CH)
 *
 * We do NOT (yet) write directly into the canonical `clickhouse_ai_events_json`
 * topic the rest of PostHog uses for `$ai_*` events. The dedicated topic gives
 * us a place to add custom logic between emit and ingestion — see
 * [`platform-llm-analytics.md`] (the "free" flag is the first such logic).
 *
 * Pattern mirrors [`log-sink.ts`](./log-sink.ts):
 *   - InMemoryAnalyticsSink (tests + local dev assertions)
 *   - NoopAnalyticsSink (dev/local without a Kafka broker)
 *   - KafkaAnalyticsSink (prod) — same node-rdkafka HighLevelProducer wrap.
 *
 * The internal `AnalyticsEvent` shape is the typed/structured one used in
 * tests. The Kafka writer translates it to the standard ClickHouse event wire
 * format (`uuid / event / properties / timestamp / team_id / distinct_id`) so
 * the future forwarder can ship rows straight into the canonical topic.
 */

import type { HighLevelProducer, LibrdKafkaError, Metadata, ProducerGlobalConfig } from 'node-rdkafka'
import { hostname } from 'node:os'
import { v4 as uuidv4 } from 'uuid'

import { createLogger } from './logger'

/**
 * Marker stamped on every event the runner produces. Future "free" /
 * platform-not-billable handling looks for this property and rewrites
 * billing meters accordingly. See `platform-llm-analytics.md` §"Future free
 * flag".
 */
export const PLATFORM_ORIGIN = 'agent_platform_runner'

/**
 * Default Kafka topic. Intentionally distinct from the canonical
 * `clickhouse_ai_events_json` so a per-platform consumer can intercept the
 * stream (add platform-origin tags, decide billable / free, rewrite for
 * special routing). Override at construction time when the consumer exists.
 */
export const DEFAULT_ANALYTICS_TOPIC = 'agent_ai_events'

/**
 * Compose a stable `distinct_id` for analytics emission. When the session
 * has a known principal (`pat`, `slack`, `internal`, …) we use
 * `<kind>:<id>` so Insights / LLM Analytics can slice per-user. For
 * anonymous public-agent sessions we fall back to `agent:<application_id>`
 * so events still bucket cleanly per agent.
 */
export function analyticsDistinctId(session: {
    application_id: string
    principal: { kind: string; id?: string } | null
}): string {
    if (session.principal && session.principal.id) {
        return `${session.principal.kind}:${session.principal.id}`
    }
    return `agent:${session.application_id}`
}

/** Stable span id for a model generation. Used as parent for tool spans in the same turn. */
export function generationSpanId(sessionId: string, turn: number): string {
    return `${sessionId}:gen:${turn}`
}

/** Stable span id for a tool dispatch. Pairs to its parent generation via `parent_span_id`. */
export function toolSpanId(sessionId: string, turn: number, toolCallId: string): string {
    return `${sessionId}:tool:${turn}:${toolCallId}`
}

/* -------------------------------------------------------------------------- */
/* Event shape — what the runner emits                                        */
/* -------------------------------------------------------------------------- */

interface AnalyticsEventBase {
    /** ISO-8601 (UTC) timestamp. */
    ts: string
    team_id: number
    application_id: string
    revision_id: string
    /** AgentSession UUID — also used as `$ai_trace_id` so all turns of a session share a trace. */
    session_id: string
    /** 1-indexed turn number within the session. */
    turn: number
    /** Stable id for this span. `<session>:<turn>` for generations; spans append `:<tool_call_id>`. */
    span_id: string
    /** Optional parent span — set on tool spans to point at the generation that emitted the toolCall. */
    parent_span_id?: string
    /** Composite — `<principal.kind>:<principal.id>` when known, else `agent:<application_id>`. */
    distinct_id: string
    /** `true` when the entry represents a failure. */
    is_error?: boolean
    /** Free-form failure detail; only set when `is_error` is true. */
    error?: string
}

export interface AnalyticsGenerationEvent extends AnalyticsEventBase {
    kind: 'generation'
    /** pi-ai resolved model id (e.g. `claude-haiku-4-5`). */
    model: string
    /** pi-ai provider name (`anthropic`, `openai`, `posthog-llm-gateway`, …). */
    provider: string
    /** Serialised user/assistant/tool message history sent into the model. */
    input: unknown[]
    /** Serialised assistant message content blocks returned by the model. */
    output: unknown
    input_tokens: number
    output_tokens: number
    cache_read_tokens?: number
    cache_write_tokens?: number
    total_tokens?: number
    /** Wall-clock duration of the pi-ai call, milliseconds. */
    latency_ms: number
    /** Total cost in USD as reported by pi-ai. Suppressed when the gateway path is in use (see useGatewayCost). */
    cost_usd?: number
    /** pi-ai stopReason — `stop`, `length`, `toolUse`, `error`, `aborted`. */
    stop_reason?: string
}

export interface AnalyticsSpanEvent extends AnalyticsEventBase {
    kind: 'span'
    /** Tool id as declared in `spec.tools` (e.g. `@posthog/query` or a custom id). */
    tool_name: string
    /** pi-ai toolCall id from the generation that produced this span. */
    tool_call_id: string
    /** Arguments after nonce substitution. Never contains plaintext secrets. */
    input: Record<string, unknown>
    /** Tool result content (text/JSON). Truncated upstream when large. */
    output: unknown
    /** Wall-clock duration of the dispatcher's tool execution, milliseconds. */
    latency_ms: number
}

export type AnalyticsEvent = AnalyticsGenerationEvent | AnalyticsSpanEvent

export interface AnalyticsSink {
    write(events: AnalyticsEvent[]): Promise<void>
}

/* -------------------------------------------------------------------------- */
/* In-memory + noop sinks (tests, local dev)                                  */
/* -------------------------------------------------------------------------- */

export class InMemoryAnalyticsSink implements AnalyticsSink {
    public readonly events: AnalyticsEvent[] = []

    async write(events: AnalyticsEvent[]): Promise<void> {
        this.events.push(...events)
    }

    /** Return events filtered by session. Most tests want this. */
    forSession(sessionId: string): AnalyticsEvent[] {
        return this.events.filter((e) => e.session_id === sessionId)
    }

    /** Convenience splits — easier than asserting on `kind` discriminator inline. */
    generations(sessionId?: string): AnalyticsGenerationEvent[] {
        const filtered = sessionId ? this.forSession(sessionId) : this.events
        return filtered.filter((e): e is AnalyticsGenerationEvent => e.kind === 'generation')
    }

    spans(sessionId?: string): AnalyticsSpanEvent[] {
        const filtered = sessionId ? this.forSession(sessionId) : this.events
        return filtered.filter((e): e is AnalyticsSpanEvent => e.kind === 'span')
    }

    clear(): void {
        this.events.length = 0
    }
}

export class NoopAnalyticsSink implements AnalyticsSink {
    async write(_events: AnalyticsEvent[]): Promise<void> {
        // intentionally empty
    }
}

/* -------------------------------------------------------------------------- */
/* Wire format — what the future consumer will read                           */
/* -------------------------------------------------------------------------- */

/**
 * Standard ClickHouse event wire row. The future `agent_ai_events`-topic
 * consumer reads this directly, optionally tags / rewrites, then forwards
 * into `clickhouse_ai_events_json` for the canonical `ai_events` materialized
 * view. Field names and types match
 * `posthog/models/ai_events/sql.py:KAFKA_AI_EVENTS_TABLE_BASE_SQL`.
 */
export interface AnalyticsWireEvent {
    uuid: string
    event: '$ai_generation' | '$ai_span'
    /** JSON-encoded property bag. Heavy fields ($ai_input, $ai_output_choices, …) are stored as raw JSON. */
    properties: string
    timestamp: string
    team_id: number
    distinct_id: string
    /** Always empty for AI events — kept to match the ClickHouse Kafka engine schema. */
    elements_chain: string
    created_at: string
    person_id: string
    person_properties: string
    person_created_at: string
    /** Matches the Enum8 in ClickHouse — `propertyless` (1) lets the consumer skip person-store lookups. */
    person_mode: 'full' | 'propertyless' | 'force_upgrade'
}

/**
 * Build the property bag from a typed `AnalyticsEvent`. Property names match
 * the schema the existing `ai_events` MV is keyed on
 * (`posthog/models/ai_events/sql.py:HEAVY_AI_PROPERTIES`) and what the
 * `llm-gateway` PostHogCallback emits.
 */
function buildProperties(event: AnalyticsEvent): Record<string, unknown> {
    const base: Record<string, unknown> = {
        $ai_trace_id: event.session_id,
        $ai_span_id: event.span_id,
        $agent_application_id: event.application_id,
        $agent_revision_id: event.revision_id,
        $agent_session_id: event.session_id,
        $agent_turn: event.turn,
        // Marker for the future "free" flag — the platform-origin consumer
        // looks for this property and rewrites billing meters accordingly.
        // Do NOT remove without coordinating with the billing consumer.
        $ai_origin: PLATFORM_ORIGIN,
    }
    if (event.parent_span_id) {
        base.$ai_parent_id = event.parent_span_id
    }
    if (event.is_error) {
        base.$ai_is_error = true
        if (event.error) {
            base.$ai_error = event.error
        }
    }
    if (event.kind === 'generation') {
        base.$ai_model = event.model
        base.$ai_provider = event.provider
        base.$ai_input = event.input
        base.$ai_output_choices = event.output
        base.$ai_input_tokens = event.input_tokens
        base.$ai_output_tokens = event.output_tokens
        if (event.cache_read_tokens !== undefined) {
            base.$ai_cache_read_input_tokens = event.cache_read_tokens
        }
        if (event.cache_write_tokens !== undefined) {
            base.$ai_cache_creation_input_tokens = event.cache_write_tokens
        }
        if (event.total_tokens !== undefined) {
            base.$ai_total_tokens = event.total_tokens
        }
        base.$ai_latency = event.latency_ms / 1000
        if (event.cost_usd !== undefined) {
            base.$ai_total_cost_usd = event.cost_usd
        }
        if (event.stop_reason) {
            base.$ai_stop_reason = event.stop_reason
        }
    } else {
        base.$ai_span_name = event.tool_name
        base.$ai_tool_call_id = event.tool_call_id
        base.$ai_input_state = event.input
        base.$ai_output_state = event.output
        base.$ai_latency = event.latency_ms / 1000
    }
    return base
}

export function toAnalyticsWire(event: AnalyticsEvent): AnalyticsWireEvent {
    return {
        uuid: uuidv4(),
        event: event.kind === 'generation' ? '$ai_generation' : '$ai_span',
        properties: JSON.stringify(buildProperties(event)),
        timestamp: event.ts,
        team_id: event.team_id,
        distinct_id: event.distinct_id,
        elements_chain: '',
        created_at: event.ts,
        person_id: '00000000-0000-0000-0000-000000000000',
        person_properties: '{}',
        person_created_at: event.ts,
        // The runner never resolves the person — let the downstream consumer
        // either fill it in or ingest propertyless rows for `agent:<app>`-style
        // distinct ids that don't correspond to real PostHog persons.
        person_mode: 'propertyless',
    }
}

/* -------------------------------------------------------------------------- */
/* Kafka sink — production path. Ports services/agent-shared/runtime/log-sink */
/* -------------------------------------------------------------------------- */

export interface KafkaAnalyticsSinkOptions {
    /** Comma-separated brokers, e.g. `kafka:9092`. */
    brokers: string
    /** Defaults to `DEFAULT_ANALYTICS_TOPIC` (`agent_ai_events`). */
    topic?: string
    /** Optional rdkafka overrides; merged over the defaults. */
    config?: Partial<ProducerGlobalConfig>
    /** Optional name for log lines / metrics labels. Defaults to topic. */
    name?: string
    /** Optional logger for connection / failure events. Defaults to the agent-shared pino. */
    logger?: {
        info: (msg: string, meta?: unknown) => void
        warn: (msg: string, meta?: unknown) => void
        error: (msg: string, meta?: unknown) => void
    }
}

const DEFAULT_PRODUCER_CONFIG: ProducerGlobalConfig = {
    'client.id': hostname(),
    'linger.ms': 20,
    'batch.size': 8 * 1024 * 1024,
    'queue.buffering.max.messages': 100_000,
    'compression.codec': 'snappy',
    'metadata.max.age.ms': 30_000,
    'socket.timeout.ms': 30_000,
}

/**
 * Production Kafka writer. Same lifecycle + lazy-load semantics as
 * `KafkaLogSink`: dynamic node-rdkafka import on first `connect()` so dev /
 * test paths don't pay the native-module cost.
 */
export class KafkaAnalyticsSink implements AnalyticsSink {
    private readonly opts: KafkaAnalyticsSinkOptions
    private readonly log: NonNullable<KafkaAnalyticsSinkOptions['logger']>
    private producer: HighLevelProducer | null = null
    private connected = false
    private connectPromise: Promise<void> | null = null
    private disposed = false

    constructor(opts: KafkaAnalyticsSinkOptions) {
        this.opts = opts
        if (opts.logger) {
            this.log = opts.logger
        } else {
            const pino = createLogger('kafka-analytics', { topic: opts.topic ?? DEFAULT_ANALYTICS_TOPIC })
            this.log = {
                info: (m, meta) => pino.info(meta ?? {}, m),
                warn: (m, meta) => pino.warn(meta ?? {}, m),
                error: (m, meta) => pino.error(meta ?? {}, m),
            }
        }
    }

    async connect(): Promise<void> {
        if (this.connected) {
            return
        }
        if (!this.connectPromise) {
            this.connectPromise = this.doConnect()
        }
        return this.connectPromise
    }

    private async doConnect(): Promise<void> {
        const rdkafka = await import('node-rdkafka')
        const merged: ProducerGlobalConfig = {
            ...DEFAULT_PRODUCER_CONFIG,
            'metadata.broker.list': this.opts.brokers,
            ...this.opts.config,
            dr_cb: false,
        }
        const producer = new rdkafka.HighLevelProducer(merged)
        producer.on('event.error', (err: LibrdKafkaError) =>
            this.log.error('rdkafka error', { name: this.opts.name ?? this.opts.topic, error: String(err) })
        )
        await new Promise<void>((resolve, reject) => {
            producer.connect(undefined, (err: LibrdKafkaError, data: Metadata) => {
                if (err) {
                    reject(err)
                    return
                }
                this.log.info('kafka analytics producer connected', {
                    name: this.opts.name ?? this.opts.topic,
                    topic: this.opts.topic ?? DEFAULT_ANALYTICS_TOPIC,
                    brokers: (data as { brokers?: unknown })?.brokers,
                })
                resolve()
            })
        })
        this.producer = producer
        this.connected = true
    }

    async write(events: AnalyticsEvent[]): Promise<void> {
        if (this.disposed) {
            return
        }
        if (!this.connected || !this.producer) {
            this.log.warn('dropping analytics events (not connected)', { count: events.length })
            return
        }
        const topic = this.opts.topic ?? DEFAULT_ANALYTICS_TOPIC
        for (const event of events) {
            const wire = toAnalyticsWire(event)
            const value = Buffer.from(safeClickhouseString(JSON.stringify(wire)))
            try {
                this.producer.produce(topic, null, value, null, Date.now(), noopDeliveryCallback)
            } catch (err) {
                this.log.error('produce failed', { topic, error: String(err) })
            }
        }
    }

    async disconnect(): Promise<void> {
        this.disposed = true
        if (!this.connected || !this.producer) {
            return
        }
        const producer = this.producer
        await new Promise<void>((resolve) =>
            producer.flush(5_000, () => {
                resolve()
            })
        )
        await new Promise<void>((resolve) =>
            producer.disconnect(() => {
                resolve()
            })
        )
        this.connected = false
        this.producer = null
    }
}

/** HighLevelProducer requires a delivery callback; we ignore it (fire-and-forget). */
function noopDeliveryCallback(): void {
    /* intentionally empty */
}

/** Same surrogate escape as `log-sink.ts`; ClickHouse's JSON parser rejects lone Unicode surrogates. */
function safeClickhouseString(str: string): string {
    return str.replace(/[\ud800-\udfff]/gu, (match) => {
        const res = JSON.stringify(match)
        return res.slice(1, res.length - 1) + `\\`
    })
}
