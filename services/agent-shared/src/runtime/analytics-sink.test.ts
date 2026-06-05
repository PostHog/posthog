import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    analyticsDistinctId,
    buildAnalyticsProperties,
    CaptureAnalyticsSink,
    eventNameFor,
    generationSpanId,
    InMemoryAnalyticsSink,
    PLATFORM_ORIGIN,
    toolSpanId,
    type AnalyticsGenerationEvent,
    type AnalyticsSpanEvent,
} from './analytics-sink'

// Mock the underlying SDK so the unit tests don't try to dial out to a
// real PostHog ingestion host. The constructor is a vi.fn so we can
// assert it gets called with the right opts (regression: previously the
// dynamic-import path meant nothing constructed CaptureAnalyticsSink in
// tests at all, so the wiring was unverified).
//
// vi.mock is hoisted above top-level `const` declarations, so the mock
// state has to be declared inside vi.hoisted() to be available when the
// factory runs.
const mocks = vi.hoisted(() => {
    const captureMock = vi.fn()
    const shutdownMock = vi.fn().mockResolvedValue(undefined)
    const postHogCtorMock = vi.fn(function (this: unknown, _key: string, _opts: unknown) {
        Object.assign(this as object, { capture: captureMock, shutdown: shutdownMock })
    })
    return { captureMock, shutdownMock, postHogCtorMock }
})
vi.mock('posthog-node', () => ({ PostHog: mocks.postHogCtorMock }))

function makeGeneration(overrides: Partial<AnalyticsGenerationEvent> = {}): AnalyticsGenerationEvent {
    return {
        kind: 'generation',
        ts: '2026-05-28T00:00:00.000Z',
        team_id: 1,
        application_id: 'app-uuid',
        revision_id: 'rev-uuid',
        session_id: 'sess-uuid',
        turn: 1,
        span_id: 'sess-uuid:gen:1',
        distinct_id: 'agent:app-uuid',
        model: 'claude-haiku-4-5',
        provider: 'anthropic',
        input: [{ role: 'user', content: 'hi' }],
        output: [{ type: 'text', text: 'hello' }],
        input_tokens: 10,
        output_tokens: 5,
        latency_ms: 1234,
        cost_usd: 0.0007,
        stop_reason: 'stop',
        ...overrides,
    }
}

function makeSpan(overrides: Partial<AnalyticsSpanEvent> = {}): AnalyticsSpanEvent {
    return {
        kind: 'span',
        ts: '2026-05-28T00:00:01.000Z',
        team_id: 1,
        application_id: 'app-uuid',
        revision_id: 'rev-uuid',
        session_id: 'sess-uuid',
        turn: 1,
        span_id: 'sess-uuid:tool:1:tc_xyz',
        parent_span_id: 'sess-uuid:gen:1',
        distinct_id: 'agent:app-uuid',
        tool_name: '@posthog/query',
        tool_call_id: 'tc_xyz',
        input: { query: 'select 1' },
        output: { rows: [], columns: [] },
        latency_ms: 42,
        ...overrides,
    }
}

describe('analyticsDistinctId', () => {
    it('uses <kind>:<id> when the principal is fully populated', () => {
        const id = analyticsDistinctId({
            application_id: 'app-uuid',
            principal: { kind: 'pat', id: 'user-7' },
        })
        expect(id).toBe('pat:user-7')
    })

    it('falls back to agent:<application_id> when there is no principal', () => {
        const id = analyticsDistinctId({ application_id: 'app-uuid', principal: null })
        expect(id).toBe('agent:app-uuid')
    })

    it('falls back to agent:<application_id> when the principal has no id', () => {
        const id = analyticsDistinctId({
            application_id: 'app-uuid',
            principal: { kind: 'anonymous' },
        })
        expect(id).toBe('agent:app-uuid')
    })
})

describe('span id helpers', () => {
    it('namespace generation spans under session + turn', () => {
        expect(generationSpanId('sess', 3)).toBe('sess:gen:3')
    })

    it('chain tool spans under their generation via the tool_call_id', () => {
        expect(toolSpanId('sess', 3, 'tc_abc')).toBe('sess:tool:3:tc_abc')
    })
})

describe('eventNameFor', () => {
    it('maps generation → $ai_generation', () => {
        expect(eventNameFor(makeGeneration())).toBe('$ai_generation')
    })

    it('maps span → $ai_span', () => {
        expect(eventNameFor(makeSpan())).toBe('$ai_span')
    })
})

describe('buildAnalyticsProperties — generation', () => {
    it('includes the $ai_* property bag PostHog LLM Analytics keys on', () => {
        const props = buildAnalyticsProperties(makeGeneration())
        expect(props.$ai_model).toBe('claude-haiku-4-5')
        expect(props.$ai_provider).toBe('anthropic')
        expect(props.$ai_input_tokens).toBe(10)
        expect(props.$ai_output_tokens).toBe(5)
        // Latency is reported as seconds (matches the $ai_latency CH column).
        expect(props.$ai_latency).toBe(1.234)
        expect(props.$ai_total_cost_usd).toBe(0.0007)
        expect(props.$ai_trace_id).toBe('sess-uuid')
        expect(props.$ai_span_id).toBe('sess-uuid:gen:1')
        expect(props.$agent_application_id).toBe('app-uuid')
        expect(props.$agent_revision_id).toBe('rev-uuid')
        // Platform-origin marker — the future signed-origin billing filter
        // keys on this property. Removing or renaming desyncs that filter.
        expect(props.$ai_origin).toBe(PLATFORM_ORIGIN)
        // team_id is stamped explicitly so per-team rollups don't need to
        // resolve through the project-key → team mapping.
        expect(props.team_id).toBe(1)
    })

    it('omits cost when not provided (gateway path)', () => {
        const props = buildAnalyticsProperties(makeGeneration({ cost_usd: undefined }))
        expect(props.$ai_total_cost_usd).toBeUndefined()
    })

    it('sets $ai_is_error + $ai_error on failed calls', () => {
        const props = buildAnalyticsProperties(
            makeGeneration({ is_error: true, error: 'rate_limit', output: null, stop_reason: undefined })
        )
        expect(props.$ai_is_error).toBe(true)
        expect(props.$ai_error).toBe('rate_limit')
        expect(props.$ai_stop_reason).toBeUndefined()
    })

    it('includes Anthropic prompt-cache token splits when present', () => {
        const props = buildAnalyticsProperties(makeGeneration({ cache_read_tokens: 7, cache_write_tokens: 3 }))
        expect(props.$ai_cache_read_input_tokens).toBe(7)
        expect(props.$ai_cache_creation_input_tokens).toBe(3)
    })
})

describe('buildAnalyticsProperties — span', () => {
    it('records span name + tool args + parent linkage', () => {
        const props = buildAnalyticsProperties(makeSpan())
        expect(props.$ai_span_name).toBe('@posthog/query')
        expect(props.$ai_tool_call_id).toBe('tc_xyz')
        expect(props.$ai_parent_id).toBe('sess-uuid:gen:1')
        expect(props.$ai_origin).toBe(PLATFORM_ORIGIN)
        expect(props.$ai_latency).toBe(0.042)
    })

    it('records error spans on tool failures', () => {
        const props = buildAnalyticsProperties(makeSpan({ is_error: true, error: 'tool_not_found', output: null }))
        expect(props.$ai_is_error).toBe(true)
        expect(props.$ai_error).toBe('tool_not_found')
    })
})

describe('InMemoryAnalyticsSink', () => {
    it('separates generations from spans for per-session assertions', async () => {
        const sink = new InMemoryAnalyticsSink()
        await sink.write([makeGeneration(), makeSpan(), makeSpan({ session_id: 'other' })])
        expect(sink.generations('sess-uuid')).toHaveLength(1)
        expect(sink.spans('sess-uuid')).toHaveLength(1)
        expect(sink.spans('other')).toHaveLength(1)
    })
})

describe('CaptureAnalyticsSink', () => {
    beforeEach(() => {
        mocks.captureMock.mockReset()
        mocks.shutdownMock.mockReset().mockResolvedValue(undefined)
        mocks.postHogCtorMock.mockClear()
    })

    it('constructs the underlying PostHog client with the configured apiKey + host + batch knobs', async () => {
        const sink = new CaptureAnalyticsSink({
            apiKey: 'phc_test_key',
            host: 'https://eu.posthog.com',
            flushAt: 5,
            flushInterval: 1_000,
        })
        await sink.connect()
        expect(mocks.postHogCtorMock).toHaveBeenCalledTimes(1)
        expect(mocks.postHogCtorMock).toHaveBeenCalledWith('phc_test_key', {
            host: 'https://eu.posthog.com',
            flushAt: 5,
            flushInterval: 1_000,
        })
    })

    it('applies sensible defaults when flushAt / flushInterval are unset', async () => {
        const sink = new CaptureAnalyticsSink({ apiKey: 'phc' })
        await sink.connect()
        expect(mocks.postHogCtorMock).toHaveBeenCalledTimes(1)
        const [, opts] = mocks.postHogCtorMock.mock.calls[0] as [string, { flushAt: number; flushInterval: number }]
        expect(opts.flushAt).toBe(20)
        expect(opts.flushInterval).toBe(10_000)
    })

    it('connect() is idempotent — concurrent + repeat calls share one client', async () => {
        const sink = new CaptureAnalyticsSink({ apiKey: 'phc' })
        await Promise.all([sink.connect(), sink.connect(), sink.connect()])
        await sink.connect()
        expect(mocks.postHogCtorMock).toHaveBeenCalledTimes(1)
    })

    it('write() routes events through capture() with the marker + namespaced event names', async () => {
        const sink = new CaptureAnalyticsSink({ apiKey: 'phc' })
        await sink.connect()
        await sink.write([makeGeneration(), makeSpan()])
        expect(mocks.captureMock).toHaveBeenCalledTimes(2)
        const generationCall = mocks.captureMock.mock.calls[0]![0] as {
            event: string
            properties: Record<string, unknown>
        }
        const spanCall = mocks.captureMock.mock.calls[1]![0] as {
            event: string
            properties: Record<string, unknown>
        }
        expect(generationCall.event).toBe('$ai_generation')
        expect(spanCall.event).toBe('$ai_span')
        expect(generationCall.properties.$ai_origin).toBe(PLATFORM_ORIGIN)
        expect(spanCall.properties.$ai_origin).toBe(PLATFORM_ORIGIN)
    })

    it('write() drops events with a single warn if connect() was never called', async () => {
        const warn = vi.fn()
        const sink = new CaptureAnalyticsSink({
            apiKey: 'phc',
            logger: { info: vi.fn(), warn, error: vi.fn() },
        })
        await sink.write([makeGeneration()])
        expect(mocks.captureMock).not.toHaveBeenCalled()
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('dropping'), { count: 1 })
    })
})
