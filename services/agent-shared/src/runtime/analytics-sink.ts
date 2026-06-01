/**
 * AnalyticsSink — the runner's LLM-analytics out-bound. One `$ai_generation`
 * per pi-ai call, one `$ai_span` per tool dispatch, captured through the
 * standard PostHog ingestion path:
 *
 *   runner ──posthog-node──▶ /capture ──ingestion──▶ clickhouse_ai_events_json ──▶ ai_events (CH)
 *
 * Hitting `/capture` (rather than producing into a dedicated Kafka topic)
 * means agent traffic shows up in LLM Analytics with zero new
 * infrastructure — same path the ai-gateway uses for its own observability
 * events.
 *
 * Sinks:
 *   - InMemoryAnalyticsSink (tests + local dev assertions)
 *   - NoopAnalyticsSink (dev/local without a PostHog destination)
 *   - CaptureAnalyticsSink (prod) — thin wrapper over posthog-node.
 *
 * Future "platform-originated == free billing" handling: every event carries
 * `$ai_origin: 'agent_platform_runner'`. The plan is to extend that into a
 * **signed marker** (HMAC over event fields with a platform secret) so a
 * downstream billing filter can verify the marker before excluding the event
 * from billable usage — a plain property is forgeable by anyone with the
 * project key. See `platform-llm-analytics.md` §"Future signed origin
 * marker". Not implemented yet; the unsigned marker is the placeholder.
 */

import type { PostHog } from 'posthog-node'

import { createLogger } from './logger'

/**
 * Marker stamped on every event the runner produces. Future signed variant
 * (see module docstring) will replace this with `$ai_origin_signature` —
 * the unsigned form here is a forgeable placeholder, fine for observability
 * but not for billing decisions until the signing work lands.
 */
export const PLATFORM_ORIGIN = 'agent_platform_runner'

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
    /** pi-ai provider name (`anthropic`, `openai`, `posthog-ai-gateway`, …). */
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
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

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

/**
 * Build the `$ai_*` property bag PostHog's LLM Analytics surface keys on.
 * Names match the existing `ai_events` MV schema
 * (`posthog/models/ai_events/sql.py:HEAVY_AI_PROPERTIES`) and what the
 * `ai-gateway` PostHogCallback emits. Exposed for tests + the future
 * signed-origin work.
 */
export function buildAnalyticsProperties(event: AnalyticsEvent): Record<string, unknown> {
    const base: Record<string, unknown> = {
        $ai_trace_id: event.session_id,
        $ai_span_id: event.span_id,
        $agent_application_id: event.application_id,
        $agent_revision_id: event.revision_id,
        $agent_session_id: event.session_id,
        $agent_turn: event.turn,
        // Marker for the future "platform-originated = free" billing filter.
        // Today this is an unsigned property — forgeable by anyone with the
        // project key. The intended evolution is a signed variant
        // (`$ai_origin_signature`) so the billing filter can verify before
        // excluding from billable usage. See module docstring + plan.
        $ai_origin: PLATFORM_ORIGIN,
        // team_id is stamped explicitly so a per-team filter / billing rollup
        // doesn't need to resolve through the project-key→team mapping.
        team_id: event.team_id,
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

export function eventNameFor(event: AnalyticsEvent): '$ai_generation' | '$ai_span' {
    return event.kind === 'generation' ? '$ai_generation' : '$ai_span'
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
/* Capture sink — production path. Goes through standard PostHog ingestion.   */
/* -------------------------------------------------------------------------- */

export interface CaptureAnalyticsSinkOptions {
    /** PostHog project API key. Same kind of key `posthog-node` takes. */
    apiKey: string
    /** Defaults to `https://us.posthog.com`. Set this to your region or self-hosted URL. */
    host?: string
    /** Optional batching tuning; defaults match `posthog-node`'s out-of-box behaviour. */
    flushAt?: number
    flushInterval?: number
    /** Optional logger for capture failures. Defaults to the agent-shared pino. */
    logger?: {
        info: (msg: string, meta?: unknown) => void
        warn: (msg: string, meta?: unknown) => void
        error: (msg: string, meta?: unknown) => void
    }
}

/**
 * Production capture sink. One `posthog-node` PostHog client per runner
 * process; events batch + flush via the SDK. `shutdown()` drains the
 * pending buffer — wire it into the runner's SIGTERM handler so events
 * don't get dropped on rolling deploys.
 *
 * `posthog-node` is loaded dynamically the first time `connect()` is called
 * so test code paths that never construct a CaptureAnalyticsSink (Noop / in
 * memory) don't pay the import cost.
 */
export class CaptureAnalyticsSink implements AnalyticsSink {
    private readonly opts: CaptureAnalyticsSinkOptions
    private readonly log: NonNullable<CaptureAnalyticsSinkOptions['logger']>
    private client: PostHog | null = null
    private connectPromise: Promise<void> | null = null

    constructor(opts: CaptureAnalyticsSinkOptions) {
        this.opts = opts
        if (opts.logger) {
            this.log = opts.logger
        } else {
            const pino = createLogger('analytics-capture')
            this.log = {
                info: (m, meta) => pino.info(meta ?? {}, m),
                warn: (m, meta) => pino.warn(meta ?? {}, m),
                error: (m, meta) => pino.error(meta ?? {}, m),
            }
        }
    }

    async connect(): Promise<void> {
        if (this.client) {
            return
        }
        if (!this.connectPromise) {
            this.connectPromise = this.doConnect()
        }
        return this.connectPromise
    }

    private async doConnect(): Promise<void> {
        const mod = await import('posthog-node')
        const PostHogCtor = mod.PostHog
        this.client = new PostHogCtor(this.opts.apiKey, {
            host: this.opts.host,
            flushAt: this.opts.flushAt ?? 20,
            flushInterval: this.opts.flushInterval ?? 10_000,
        })
        this.log.info('capture analytics sink connected', { host: this.opts.host ?? 'default' })
    }

    async write(events: AnalyticsEvent[]): Promise<void> {
        if (!this.client) {
            this.log.warn('dropping analytics events (not connected)', { count: events.length })
            return
        }
        for (const event of events) {
            try {
                this.client.capture({
                    distinctId: event.distinct_id,
                    event: eventNameFor(event),
                    properties: buildAnalyticsProperties(event),
                    groups: { project: String(event.team_id) },
                    timestamp: new Date(event.ts),
                })
            } catch (err) {
                this.log.error('capture failed', { event: eventNameFor(event), error: String(err) })
            }
        }
    }

    /**
     * Drains the SDK's pending buffer + shuts down. Production wires this
     * into the SIGTERM handler so a rolling deploy doesn't drop the last
     * batch.
     */
    async shutdown(): Promise<void> {
        if (!this.client) {
            return
        }
        try {
            await this.client.shutdown()
        } catch (err) {
            this.log.error('capture shutdown failed', { error: String(err) })
        }
        this.client = null
    }
}
