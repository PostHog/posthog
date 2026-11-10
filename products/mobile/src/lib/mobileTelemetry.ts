import { SpanKind, SpanStatusCode, trace } from '@opentelemetry/api'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { BasicTracerProvider, BatchSpanProcessor, TraceIdRatioBasedSampler } from '@opentelemetry/sdk-trace-base'
import { AppState } from 'react-native'

const INSTRUMENTATION_NAME = 'posthog-mobile'
const SLOW_REQUEST_MS = 2000
// Django samples with parentbased_traceidratio and follows the sampled flag in `traceparent`.
// This ratio therefore also sets how many mobile API requests Django traces end to end.
const TRACE_SAMPLE_RATIO = 0.1

type Log = (level: 'warn' | 'error', body: string, attributes: Record<string, string | number>) => void

let started = false
let requestTracer = trace.getTracer(INSTRUMENTATION_NAME)
let log: Log | undefined
let isEnabled: () => boolean = () => false
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

export function initMobileTelemetry(apiKey: string, host: string, logRequest: Log, enabled: () => boolean): void {
    telemetryConfig = { apiKey, host }
    log = logRequest
    isEnabled = enabled
}

function ensureTelemetry(): boolean {
    if (started) return true
    if (!telemetryConfig) return false
    try {
        startTelemetry(telemetryConfig)
        started = true
        return true
    } catch {
        // A bad export host disables telemetry for this process instead of failing every API request.
        telemetryConfig = undefined
        return false
    }
}

function startTelemetry({ apiKey, host }: { apiKey: string; host: string }): void {
    const headers = { Authorization: `Bearer ${apiKey}` }
    const traces = new OTLPTraceExporter({ url: `${host.replace(/\/$/, '')}/i/v1/traces`, headers })
    const provider = new BasicTracerProvider({
        resource: resourceFromAttributes({ 'service.name': INSTRUMENTATION_NAME }),
        sampler: new TraceIdRatioBasedSampler(TRACE_SAMPLE_RATIO),
        spanProcessors: [new BatchSpanProcessor(traces, { scheduledDelayMillis: 5000, maxExportBatchSize: 32 })],
    })
    requestTracer = provider.getTracer(INSTRUMENTATION_NAME)

    // The OS can end a backgrounded app before the export timer fires.
    AppState.addEventListener('change', (state) => {
        if (state === 'background') {
            void provider.forceFlush().catch(() => {})
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

function isDeadlineTimeout(signal: AbortSignal | null | undefined): boolean {
    return signal?.reason instanceof Error && signal.reason.name === 'RequestTimeoutError'
}

export async function instrumentApiRequest(
    path: string,
    method: string,
    request: (traceparent?: string) => Promise<Response>,
    signal?: AbortSignal | null
): Promise<Response> {
    if (!isEnabled() || !ensureTelemetry()) return request()

    const route = routeForPath(path)
    const attributes = { 'http.request.method': method.toUpperCase(), 'http.route': route }
    const span = requestTracer.startSpan(`${method.toUpperCase()} ${route}`, { kind: SpanKind.CLIENT, attributes })
    const spanContext = span.spanContext()
    const traceparent = `00-${spanContext.traceId}-${spanContext.spanId}-${(spanContext.traceFlags ?? 0).toString(16).padStart(2, '0')}`
    const traceIds: Record<string, string> = span.isRecording()
        ? { trace_id: spanContext.traceId, span_id: spanContext.spanId }
        : {}
    const startedAt = Date.now()
    try {
        const result = await request(traceparent)
        recordSafely(() => {
            const status = result.status
            const durationMs = Date.now() - startedAt
            const failed = status >= 400
            span.setAttribute('http.response.status_code', status)
            if (failed) span.setStatus({ code: SpanStatusCode.ERROR })
            if (failed || durationMs >= SLOW_REQUEST_MS) {
                log?.(
                    failed ? 'error' : 'warn',
                    failed ? 'Mobile API request failed' : 'Mobile API request completed',
                    {
                        ...attributes,
                        'http.response.status_code': status,
                        duration_ms: durationMs,
                        ...traceIds,
                    }
                )
            }
        })
        return result
    } catch (error) {
        if (!isCancelled(error) || isDeadlineTimeout(signal)) {
            recordSafely(() => {
                const durationMs = Date.now() - startedAt
                const failure: unknown = isDeadlineTimeout(signal) ? signal?.reason : error
                const candidateErrorType = failure instanceof Error ? failure.name : ''
                const errorType = /^[A-Za-z][A-Za-z0-9]{0,39}$/.test(candidateErrorType)
                    ? candidateErrorType
                    : 'NetworkError'
                span.setAttribute('error.type', errorType)
                span.setStatus({ code: SpanStatusCode.ERROR })
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
