import { SpanKind, SpanStatusCode, trace } from '@opentelemetry/api'
import { AggregationTemporalityPreference, OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { BasicTracerProvider, BatchSpanProcessor } from '@opentelemetry/sdk-trace-base'
import { AppState } from 'react-native'

import { FEATURE_FLAGS, isFeatureFlagEnabled } from './featureFlags'

const INSTRUMENTATION_NAME = 'posthog-mobile'
const SLOW_REQUEST_MS = 2000
// The OpenTelemetry semantic convention boundaries for HTTP durations in seconds.
const REQUEST_DURATION_BUCKETS_S = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]

type Log = (level: 'warn' | 'error', body: string, attributes: Record<string, string | number>) => void

let requestDuration: ReturnType<ReturnType<MeterProvider['getMeter']>['createHistogram']> | undefined
let requestTracer = trace.getTracer(INSTRUMENTATION_NAME)
let log: Log | undefined
let telemetryConfig: { apiKey: string; host: string } | undefined

// Every other path segment is an identifier, so an unknown ID format can never add a new route series.
const ROUTE_SEGMENTS: ReadonlySet<string> = new Set([
    '@me',
    'api',
    'artefacts',
    'artifacts',
    'assign',
    'available_reviewers',
    'command',
    'config',
    'dashboards',
    'error_tracking',
    'file_system_shortcut',
    'finalize_upload',
    'inline_scan',
    'insights',
    'issue',
    'issue_events',
    'issues',
    'logs',
    'models',
    'observations',
    'organizations',
    'page',
    'pr_checks',
    'prepare_upload',
    'projects',
    'push_tokens',
    'query',
    'read_state',
    'reports',
    'reviewers',
    'run',
    'runs',
    'scanners',
    'session_recordings',
    'signals',
    'spike_events',
    'staged_artifacts',
    'state',
    'stream',
    'tasks',
    'thumbnail',
    'today',
    'unregister',
    'users',
    'viewed',
    'vision',
    'watch_feed',
])

export function routeForPath(path: string): string {
    const pathOnly = path.split(/[?#]/, 1)[0] || '/'
    return pathOnly
        .split('/')
        .map((part) => (!part || ROUTE_SEGMENTS.has(part) ? part : ':id'))
        .join('/')
}

export function initMobileTelemetry(apiKey: string, host: string, logRequest: Log): void {
    telemetryConfig = { apiKey, host }
    log = logRequest
}

function ensureTelemetry(): boolean {
    if (requestDuration) return true
    if (!telemetryConfig) return false
    try {
        startTelemetry(telemetryConfig)
        return true
    } catch {
        // A bad export host disables telemetry for this process instead of failing every API request.
        telemetryConfig = undefined
        return false
    }
}

function startTelemetry({ apiKey, host }: { apiKey: string; host: string }): void {
    const headers = { Authorization: `Bearer ${apiKey}` }
    const resource = resourceFromAttributes({ 'service.name': INSTRUMENTATION_NAME })
    const traces = new OTLPTraceExporter({ url: `${host.replace(/\/$/, '')}/i/v1/traces`, headers })
    const provider = new BasicTracerProvider({
        resource,
        spanProcessors: [new BatchSpanProcessor(traces, { scheduledDelayMillis: 5000, maxExportBatchSize: 32 })],
    })
    requestTracer = provider.getTracer(INSTRUMENTATION_NAME)

    // Delta sends each measurement once, so an idle app exports nothing and phones do not mix running totals.
    const metrics = new OTLPMetricExporter({
        url: `${host.replace(/\/$/, '')}/i/v1/metrics`,
        headers,
        temporalityPreference: AggregationTemporalityPreference.DELTA,
    })
    const meterProvider = new MeterProvider({
        resource,
        readers: [new PeriodicExportingMetricReader({ exporter: metrics, exportIntervalMillis: 30000 })],
    })
    requestDuration = meterProvider.getMeter(INSTRUMENTATION_NAME).createHistogram('http.client.request.duration', {
        description: 'Duration of mobile API requests',
        unit: 's',
        advice: { explicitBucketBoundaries: REQUEST_DURATION_BUCKETS_S },
    })
    // The OS can end a backgrounded app before the export timers fire.
    AppState.addEventListener('change', (state) => {
        if (state === 'background') {
            void provider.forceFlush()
            void meterProvider.forceFlush()
        }
    })
}

// Telemetry must never change the result of the request it measures.
function recordSafely(record: () => void): void {
    try {
        record()
    } catch {}
}

function isCancelled(error: unknown): boolean {
    return error instanceof Error && error.name === 'AbortError'
}

export async function instrumentApiRequest(
    path: string,
    method: string,
    request: (traceparent?: string) => Promise<Response>
): Promise<Response> {
    if (!isFeatureFlagEnabled(FEATURE_FLAGS.networkObservability) || !ensureTelemetry()) return request()

    const route = routeForPath(path)
    const attributes = { 'http.request.method': method.toUpperCase(), 'http.route': route }
    const span = requestTracer.startSpan(`${method.toUpperCase()} ${route}`, { kind: SpanKind.CLIENT, attributes })
    const spanContext = span.spanContext()
    const traceparent = `00-${spanContext.traceId}-${spanContext.spanId}-${(spanContext.traceFlags ?? 0).toString(16).padStart(2, '0')}`
    const traceIds = { trace_id: spanContext.traceId, span_id: spanContext.spanId }
    const startedAt = Date.now()
    try {
        const result = await request(traceparent)
        recordSafely(() => {
            const status = result.status
            const durationMs = Date.now() - startedAt
            span.setAttribute('http.response.status_code', status)
            if (status >= 500) span.setStatus({ code: SpanStatusCode.ERROR })
            requestDuration?.record(durationMs / 1000, { ...attributes, 'http.response.status_code': status })
            if (status >= 500 || durationMs >= SLOW_REQUEST_MS) {
                log?.(status >= 500 ? 'error' : 'warn', 'Mobile API request completed', {
                    ...attributes,
                    'http.response.status_code': status,
                    duration_ms: durationMs,
                    ...traceIds,
                })
            }
        })
        return result
    } catch (error) {
        if (!isCancelled(error)) {
            recordSafely(() => {
                const durationMs = Date.now() - startedAt
                const candidateErrorType = error instanceof Error ? error.name : ''
                const errorType = /^[A-Za-z][A-Za-z0-9]{0,39}$/.test(candidateErrorType)
                    ? candidateErrorType
                    : 'NetworkError'
                span.setAttribute('error.type', errorType)
                span.setStatus({ code: SpanStatusCode.ERROR })
                requestDuration?.record(durationMs / 1000, { ...attributes, 'error.type': errorType })
                log?.('error', 'Mobile API request failed', {
                    ...attributes,
                    duration_ms: durationMs,
                    'error.type': errorType,
                    ...traceIds,
                })
            })
        }
        throw error
    } finally {
        recordSafely(() => span.end())
    }
}
