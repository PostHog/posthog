import { SpanKind, SpanStatusCode, trace } from '@opentelemetry/api'
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { BasicTracerProvider, BatchSpanProcessor } from '@opentelemetry/sdk-trace-base'

import { FEATURE_FLAGS, isFeatureFlagEnabled } from './featureFlags'

const INSTRUMENTATION_NAME = 'posthog-mobile'
const SLOW_REQUEST_MS = 2000

type Log = (level: 'warn' | 'error', body: string, attributes: Record<string, string | number>) => void

let requestDuration: ReturnType<ReturnType<MeterProvider['getMeter']>['createHistogram']> | undefined
let requestTracer = trace.getTracer(INSTRUMENTATION_NAME)
let log: Log | undefined
let telemetryConfig: { apiKey: string; host: string } | undefined

function routeForPath(path: string): string {
    const pathOnly = path.split(/[?#]/, 1)[0] || '/'
    return pathOnly
        .split('/')
        .map((part, index, parts) => {
            if (!part) return part
            if (/^\d+$/.test(part) || /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(part) || part.length > 40) return ':id'
            if (
                index > 0 &&
                /^(?:apps|cohorts|conversations|dashboards|events|files|flags|integrations|messages|organizations|projects|reports|runs|sessions|tasks|users)$/.test(
                    parts[index - 1] ?? ''
                )
            ) {
                return ':id'
            }
            if (part.includes('@') || /[^a-z0-9_-]/i.test(part)) return ':id'
            return part
        })
        .join('/')
}

export function initMobileTelemetry(apiKey: string, host: string, logRequest: Log): void {
    telemetryConfig = { apiKey, host }
    log = logRequest
}

function ensureTelemetry(): boolean {
    if (requestDuration) return true
    if (!telemetryConfig) return false

    const { apiKey, host } = telemetryConfig
    const headers = { Authorization: `Bearer ${apiKey}` }
    const resource = resourceFromAttributes({ 'service.name': INSTRUMENTATION_NAME })
    const traces = new OTLPTraceExporter({ url: `${host.replace(/\/$/, '')}/i/v1/traces`, headers })
    const provider = new BasicTracerProvider({
        resource,
        spanProcessors: [new BatchSpanProcessor(traces, { scheduledDelayMillis: 5000, maxExportBatchSize: 32 })],
    })
    requestTracer = provider.getTracer(INSTRUMENTATION_NAME)

    const metrics = new OTLPMetricExporter({ url: `${host.replace(/\/$/, '')}/i/v1/metrics`, headers })
    const meterProvider = new MeterProvider({
        resource,
        readers: [new PeriodicExportingMetricReader({ exporter: metrics, exportIntervalMillis: 30000 })],
    })
    requestDuration = meterProvider.getMeter(INSTRUMENTATION_NAME).createHistogram('http.client.request.duration', {
        description: 'Duration of mobile API requests',
        unit: 's',
    })
    return true
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
    const startedAt = Date.now()
    try {
        const result = await request(traceparent)
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
                trace_id: spanContext.traceId,
                span_id: spanContext.spanId,
            })
        }
        return result
    } catch (error) {
        const durationMs = Date.now() - startedAt
        const candidateErrorType = error instanceof Error ? error.name : ''
        const errorType = /^[A-Za-z][A-Za-z0-9]{0,39}$/.test(candidateErrorType) ? candidateErrorType : 'NetworkError'
        span.setAttribute('error.type', errorType)
        span.setStatus({ code: SpanStatusCode.ERROR })
        requestDuration?.record(durationMs / 1000, { ...attributes, 'error.type': errorType })
        log?.('error', 'Mobile API request failed', {
            ...attributes,
            duration_ms: durationMs,
            'error.type': errorType,
            trace_id: spanContext.traceId,
            span_id: spanContext.spanId,
        })
        throw error
    } finally {
        span.end()
    }
}
