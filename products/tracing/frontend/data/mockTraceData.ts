// Types aligned with OTel Span specification and PostHog conventions
// Field naming follows PostHog's snake_case pattern (matching logs infrastructure)
// Attribute values are all strings (matching PostHog ClickHouse storage: Map(LowCardinality(String), String))

export type StatusCode = 'unset' | 'ok' | 'error'
export type SpanKind = 'server' | 'client' | 'producer' | 'consumer' | 'internal'

export interface SpanEvent {
    name: string
    timestamp: string
    attributes: Record<string, string>
}

export interface SpanLink {
    trace_id: string
    span_id: string
    trace_flags: number
    trace_state: string
    attributes: Record<string, string>
}

export interface Span {
    uuid: string
    trace_id: string
    span_id: string
    parent_span_id: string // empty string for root spans (matches PostHog ClickHouse convention)
    trace_flags: number
    name: string
    span_kind: SpanKind
    status_code: StatusCode
    status_message: string
    timestamp: string // ISO 8601 start time
    end_timestamp: string // ISO 8601 end time (span-specific, not present on logs)
    duration_ms: number
    service_name: string // extracted from resource_attributes['service.name']
    resource_attributes: Record<string, string>
    instrumentation_scope: string // format: "name@version"
    attributes: Record<string, string>
    events: SpanEvent[]
    links: SpanLink[]
}

// Trace summary — derived from spans, as the backend would compute it
export interface TraceSummary {
    trace_id: string
    root_service_name: string
    root_span_name: string
    status_code: StatusCode
    duration_ms: number
    span_count: number
    timestamp: string
    spans: Span[]
}

// --- Helpers ---

const now = Date.now()
const hour = 3600_000
const minute = 60_000

let _uuidSeq = 0
function nextUuid(): string {
    _uuidSeq++
    const hex = _uuidSeq.toString(16).padStart(4, '0')
    return `0190a001-${hex}-7000-8000-000000000000`
}

function ts(ms: number): string {
    return new Date(ms).toISOString()
}

const DEFAULT_SDK: Record<string, string> = {
    'telemetry.sdk.language': 'node',
    'telemetry.sdk.name': 'opentelemetry',
    'telemetry.sdk.version': '1.24.0',
    'deployment.environment': 'production',
}

function resourceAttrs(serviceName: string, extra?: Record<string, string>): Record<string, string> {
    return {
        'service.name': serviceName,
        ...DEFAULT_SDK,
        ...extra,
    }
}

interface MakeSpanOpts {
    span_id: string
    parent_span_id?: string
    name: string
    service_name: string
    span_kind: SpanKind
    status_code?: StatusCode
    status_message?: string
    offset_ms: number
    duration_ms: number
    attributes?: Record<string, string>
    resource_extra?: Record<string, string>
    instrumentation_scope?: string
    events?: SpanEvent[]
    links?: SpanLink[]
}

function makeSpan(traceId: string, baseMs: number, opts: MakeSpanOpts): Span {
    const startMs = baseMs + opts.offset_ms
    return {
        uuid: nextUuid(),
        trace_id: traceId,
        span_id: opts.span_id,
        parent_span_id: opts.parent_span_id ?? '',
        trace_flags: 1,
        name: opts.name,
        span_kind: opts.span_kind,
        status_code: opts.status_code ?? 'ok',
        status_message: opts.status_message ?? '',
        timestamp: ts(startMs),
        end_timestamp: ts(startMs + opts.duration_ms),
        duration_ms: opts.duration_ms,
        service_name: opts.service_name,
        resource_attributes: resourceAttrs(opts.service_name, opts.resource_extra),
        instrumentation_scope: opts.instrumentation_scope ?? '@opentelemetry/auto-instrumentations-node@0.41.0',
        attributes: opts.attributes ?? {},
        events: opts.events ?? [],
        links: opts.links ?? [],
    }
}

function makeTrace(spans: Span[]): TraceSummary {
    const rootSpan = spans.find((s) => s.parent_span_id === '') ?? spans[0]
    const hasError = spans.some((s) => s.status_code === 'error')
    return {
        trace_id: rootSpan.trace_id,
        root_service_name: rootSpan.service_name,
        root_span_name: rootSpan.name,
        status_code: hasError ? 'error' : rootSpan.status_code,
        duration_ms: rootSpan.duration_ms,
        span_count: spans.length,
        timestamp: rootSpan.timestamp,
        spans,
    }
}

// --- Mock traces ---

// Trace 1: Successful user lookup
const t1 = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
const t1Base = now - 2 * minute

// Trace 2: Failed checkout — payment gateway timeout
const t2 = 'b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a1'
const t2Base = now - 5 * minute

// Trace 3: Fast product search with cache hit
const t3 = 'c3d4e5f6a7b8c9d0e1f2a3b4c5d6a1b2'
const t3Base = now - 8 * minute

// Trace 4: Batch email processing (long-running)
const t4 = 'd4e5f6a7b8c9d0e1f2a3b4c5d6a1b2c3'
const t4Base = now - 15 * minute

// Trace 5: User profile update
const t5 = 'e5f6a7b8c9d0e1f2a3b4c5d6a1b2c3d4'
const t5Base = now - 22 * minute

// Trace 6: Fast event ingestion
const t6 = 'f6a7b8c9d0e1f2a3b4c5d6a1b2c3d4e5'
const t6Base = now - 30 * minute

// Trace 7: Session cleanup failure — connection pool exhausted
const t7 = 'a7b8c9d0e1f2a3b4c5d6a1b2c3d4e5f6'
const t7Base = now - 45 * minute

// Trace 8: Dashboard aggregation
const t8 = 'b8c9d0e1f2a3b4c5d6a1b2c3d4e5f6a7'
const t8Base = now - 1 * hour

// Trace 9: Stripe webhook
const t9 = 'c9d0e1f2a3b4c5d6a1b2c3d4e5f6a7b8'
const t9Base = now - 2 * hour

// Trace 10: Feature flag evaluation (very fast)
const t10 = 'd0e1f2a3b4c5d6a1b2c3d4e5f6a7b8c9'
const t10Base = now - 3 * hour

export const MOCK_TRACES: TraceSummary[] = [
    // 1: GET /api/users — 5 spans, 245ms, OK
    makeTrace([
        makeSpan(t1, t1Base, {
            span_id: 'a1b2c3d4e5f6a7b8',
            name: 'GET /api/users',
            service_name: 'api-gateway',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 245,
            attributes: { 'http.method': 'GET', 'http.route': '/api/users', 'http.status_code': '200' },
            resource_extra: { 'service.version': '2.4.1', 'host.name': 'api-gw-prod-01' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t1, t1Base, {
            span_id: '2f4a8b1c3d5e6f7a',
            parent_span_id: 'a1b2c3d4e5f6a7b8',
            name: 'verify-token',
            service_name: 'auth-service',
            span_kind: 'client',
            offset_ms: 5,
            duration_ms: 42,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'VerifyToken', 'rpc.grpc.status_code': '0' },
            resource_extra: { 'service.version': '1.8.0' },
        }),
        makeSpan(t1, t1Base, {
            span_id: '3a5b7c9d1e3f5a7b',
            parent_span_id: 'a1b2c3d4e5f6a7b8',
            name: 'get-user',
            service_name: 'user-service',
            span_kind: 'client',
            offset_ms: 52,
            duration_ms: 185,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'GetUser' },
            resource_extra: { 'service.version': '3.1.2' },
        }),
        makeSpan(t1, t1Base, {
            span_id: '4c6d8e0f2a4b6c8d',
            parent_span_id: '3a5b7c9d1e3f5a7b',
            name: 'SELECT * FROM users WHERE id = $1',
            service_name: 'postgres',
            span_kind: 'client',
            offset_ms: 60,
            duration_ms: 65,
            attributes: {
                'db.system': 'postgresql',
                'db.name': 'users_db',
                'db.statement': 'SELECT * FROM users WHERE id = $1',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
        makeSpan(t1, t1Base, {
            span_id: '5d7e9f1a3b5c7d9e',
            parent_span_id: '3a5b7c9d1e3f5a7b',
            name: 'GET user:usr_12345',
            service_name: 'redis',
            span_kind: 'client',
            offset_ms: 55,
            duration_ms: 3,
            attributes: { 'db.system': 'redis', 'db.operation': 'GET', 'cache.hit': 'false' },
            instrumentation_scope: '@opentelemetry/instrumentation-redis@0.38.0',
        }),
    ]),

    // 2: POST /api/checkout — 8 spans, 1243ms, ERROR (payment timeout)
    makeTrace([
        makeSpan(t2, t2Base, {
            span_id: 'b1a2c3d4e5f67890',
            name: 'POST /api/checkout',
            service_name: 'web-app',
            span_kind: 'server',
            status_code: 'error',
            status_message: 'Payment gateway timeout',
            offset_ms: 0,
            duration_ms: 1243,
            attributes: { 'http.method': 'POST', 'http.route': '/api/checkout', 'http.status_code': '504' },
            resource_extra: { 'service.version': '4.2.0', 'host.name': 'web-prod-03' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b2f4a8b1c3d5e6f7',
            parent_span_id: 'b1a2c3d4e5f67890',
            name: 'validate-cart',
            service_name: 'cart-service',
            span_kind: 'client',
            offset_ms: 8,
            duration_ms: 35,
            attributes: {
                'rpc.system': 'grpc',
                'rpc.method': 'ValidateCart',
                'cart.items': '3',
                'cart.total': '149.99',
            },
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b3a5b7c9d1e3f5a7',
            parent_span_id: 'b1a2c3d4e5f67890',
            name: 'charge',
            service_name: 'payment-service',
            span_kind: 'client',
            status_code: 'error',
            status_message: 'Upstream timeout after 1000ms',
            offset_ms: 50,
            duration_ms: 1100,
            attributes: { 'payment.provider': 'stripe', 'payment.amount': '149.99', 'payment.currency': 'USD' },
            events: [
                {
                    name: 'exception',
                    timestamp: ts(t2Base + 1150),
                    attributes: {
                        'exception.type': 'TimeoutError',
                        'exception.message': 'Upstream timeout after 1000ms waiting for stripe API',
                        'exception.stacktrace':
                            'TimeoutError: Upstream timeout after 1000ms\n    at StripeClient.charge (payment-service/src/stripe.ts:42)\n    at PaymentHandler.process (payment-service/src/handler.ts:18)',
                    },
                },
            ],
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b4c6d8e0f2a4b6c8',
            parent_span_id: 'b3a5b7c9d1e3f5a7',
            name: 'POST /v1/charges',
            service_name: 'stripe-client',
            span_kind: 'client',
            status_code: 'error',
            status_message: 'Connection timeout',
            offset_ms: 55,
            duration_ms: 1000,
            attributes: {
                'http.method': 'POST',
                'http.url': 'https://api.stripe.com/v1/charges',
                'net.peer.name': 'api.stripe.com',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b5d7e9f1a3b5c7d9',
            parent_span_id: 'b1a2c3d4e5f67890',
            name: 'reserve-inventory',
            service_name: 'inventory-service',
            span_kind: 'client',
            offset_ms: 45,
            duration_ms: 28,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'ReserveInventory', 'inventory.sku_count': '3' },
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b6e8f0a2b4c6d8e0',
            parent_span_id: 'b5d7e9f1a3b5c7d9',
            name: 'UPDATE inventory SET reserved = reserved + 1',
            service_name: 'postgres',
            span_kind: 'client',
            offset_ms: 48,
            duration_ms: 18,
            attributes: { 'db.system': 'postgresql', 'db.name': 'inventory_db', 'db.operation': 'UPDATE' },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b7f9a1b3c5d7e9f1',
            parent_span_id: 'b1a2c3d4e5f67890',
            name: 'publish order.failed',
            service_name: 'kafka-producer',
            span_kind: 'producer',
            offset_ms: 1160,
            duration_ms: 15,
            attributes: {
                'messaging.system': 'kafka',
                'messaging.destination': 'order.events',
                'messaging.operation': 'publish',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-kafkajs@0.1.0',
        }),
        makeSpan(t2, t2Base, {
            span_id: 'b8a0b2c4d6e8f0a2',
            parent_span_id: 'b1a2c3d4e5f67890',
            name: 'send-failure-email',
            service_name: 'notification-service',
            span_kind: 'client',
            offset_ms: 1180,
            duration_ms: 52,
            attributes: { 'email.template': 'order_failed', 'email.recipient': 'user@example.com' },
        }),
    ]),

    // 3: GET /api/products — 3 spans, 89ms, OK (cache hit)
    makeTrace([
        makeSpan(t3, t3Base, {
            span_id: 'c1a2b3c4d5e6f7a8',
            name: 'GET /api/products',
            service_name: 'api-gateway',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 89,
            attributes: { 'http.method': 'GET', 'http.route': '/api/products', 'http.status_code': '200' },
            resource_extra: { 'service.version': '2.4.1' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t3, t3Base, {
            span_id: 'c2b3c4d5e6f7a8b9',
            parent_span_id: 'c1a2b3c4d5e6f7a8',
            name: 'GET products:electronics',
            service_name: 'redis',
            span_kind: 'client',
            offset_ms: 3,
            duration_ms: 2,
            attributes: { 'db.system': 'redis', 'db.operation': 'GET', 'cache.hit': 'true' },
            instrumentation_scope: '@opentelemetry/instrumentation-redis@0.38.0',
        }),
        makeSpan(t3, t3Base, {
            span_id: 'c3c4d5e6f7a8b9c0',
            parent_span_id: 'c1a2b3c4d5e6f7a8',
            name: 'product-search',
            service_name: 'search-service',
            span_kind: 'client',
            offset_ms: 8,
            duration_ms: 75,
            attributes: {
                'search.engine': 'elasticsearch',
                'search.results': '24',
                'search.query': 'category:electronics',
            },
        }),
    ]),

    // 4: Batch email processing — 4 spans, 3450ms, OK (long-running)
    makeTrace([
        makeSpan(t4, t4Base, {
            span_id: 'd1a2b3c4d5e6f7a8',
            name: 'process-batch-emails',
            service_name: 'cron-worker',
            span_kind: 'internal',
            offset_ms: 0,
            duration_ms: 3450,
            attributes: { 'batch.size': '150', 'batch.type': 'marketing' },
            resource_extra: { 'service.version': '1.3.0', 'host.name': 'worker-prod-02' },
        }),
        makeSpan(t4, t4Base, {
            span_id: 'd2b3c4d5e6f7a8b9',
            parent_span_id: 'd1a2b3c4d5e6f7a8',
            name: 'SELECT * FROM email_queue LIMIT 150',
            service_name: 'postgres',
            span_kind: 'client',
            offset_ms: 5,
            duration_ms: 45,
            attributes: { 'db.system': 'postgresql', 'db.name': 'notifications_db', 'db.rows_affected': '150' },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
        makeSpan(t4, t4Base, {
            span_id: 'd3c4d5e6f7a8b9c0',
            parent_span_id: 'd1a2b3c4d5e6f7a8',
            name: 'send-batch',
            service_name: 'ses-client',
            span_kind: 'client',
            offset_ms: 55,
            duration_ms: 3200,
            attributes: {
                'email.provider': 'aws-ses',
                'email.count': '150',
                'email.success': '148',
                'email.failed': '2',
            },
        }),
        makeSpan(t4, t4Base, {
            span_id: 'd4d5e6f7a8b9c0d1',
            parent_span_id: 'd1a2b3c4d5e6f7a8',
            name: 'publish email.batch.completed',
            service_name: 'kafka-producer',
            span_kind: 'producer',
            offset_ms: 3260,
            duration_ms: 8,
            attributes: {
                'messaging.system': 'kafka',
                'messaging.destination': 'email.events',
                'messaging.operation': 'publish',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-kafkajs@0.1.0',
        }),
    ]),

    // 5: PUT /api/users/profile — 4 spans, 178ms, OK
    makeTrace([
        makeSpan(t5, t5Base, {
            span_id: 'e1a2b3c4d5e6f7a8',
            name: 'PUT /api/users/profile',
            service_name: 'api-gateway',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 178,
            attributes: { 'http.method': 'PUT', 'http.route': '/api/users/profile', 'http.status_code': '200' },
            resource_extra: { 'service.version': '2.4.1' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t5, t5Base, {
            span_id: 'e2b3c4d5e6f7a8b9',
            parent_span_id: 'e1a2b3c4d5e6f7a8',
            name: 'verify-token',
            service_name: 'auth-service',
            span_kind: 'client',
            offset_ms: 3,
            duration_ms: 38,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'VerifyToken' },
        }),
        makeSpan(t5, t5Base, {
            span_id: 'e3c4d5e6f7a8b9c0',
            parent_span_id: 'e1a2b3c4d5e6f7a8',
            name: 'update-user',
            service_name: 'user-service',
            span_kind: 'client',
            offset_ms: 45,
            duration_ms: 125,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'UpdateUser' },
        }),
        makeSpan(t5, t5Base, {
            span_id: 'e4d5e6f7a8b9c0d1',
            parent_span_id: 'e3c4d5e6f7a8b9c0',
            name: 'UPDATE users SET name = $1 WHERE id = $2',
            service_name: 'postgres',
            span_kind: 'client',
            offset_ms: 50,
            duration_ms: 32,
            attributes: { 'db.system': 'postgresql', 'db.name': 'users_db', 'db.rows_affected': '1' },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
    ]),

    // 6: POST /api/events — 2 spans, 12ms, OK (fast ingestion)
    makeTrace([
        makeSpan(t6, t6Base, {
            span_id: 'f1a2b3c4d5e6f7a8',
            name: 'POST /api/events',
            service_name: 'web-app',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 12,
            attributes: {
                'http.method': 'POST',
                'http.route': '/api/events',
                'http.status_code': '202',
                'events.count': '5',
            },
            resource_extra: { 'service.version': '4.2.0' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t6, t6Base, {
            span_id: 'f2b3c4d5e6f7a8b9',
            parent_span_id: 'f1a2b3c4d5e6f7a8',
            name: 'publish events.ingest',
            service_name: 'kafka-producer',
            span_kind: 'producer',
            offset_ms: 2,
            duration_ms: 6,
            attributes: {
                'messaging.system': 'kafka',
                'messaging.destination': 'events.ingest',
                'messaging.batch_size': '5',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-kafkajs@0.1.0',
        }),
    ]),

    // 7: DELETE /api/sessions/expired — 3 spans, 520ms, ERROR (pool exhausted)
    makeTrace([
        makeSpan(t7, t7Base, {
            span_id: 'a7a2b3c4d5e6f7a8',
            name: 'DELETE /api/sessions/expired',
            service_name: 'api-gateway',
            span_kind: 'server',
            status_code: 'error',
            status_message: 'Internal server error',
            offset_ms: 0,
            duration_ms: 520,
            attributes: { 'http.method': 'DELETE', 'http.route': '/api/sessions/expired', 'http.status_code': '500' },
            resource_extra: { 'service.version': '2.4.1' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t7, t7Base, {
            span_id: 'a7b3c4d5e6f7a8b9',
            parent_span_id: 'a7a2b3c4d5e6f7a8',
            name: 'delete-expired-sessions',
            service_name: 'session-service',
            span_kind: 'client',
            status_code: 'error',
            status_message: 'Connection pool exhausted',
            offset_ms: 8,
            duration_ms: 505,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'DeleteExpiredSessions' },
            events: [
                {
                    name: 'exception',
                    timestamp: ts(t7Base + 513),
                    attributes: {
                        'exception.type': 'ConnectionPoolError',
                        'exception.message': 'Connection pool exhausted: 50/50 connections in use',
                    },
                },
            ],
        }),
        makeSpan(t7, t7Base, {
            span_id: 'a7c4d5e6f7a8b9c0',
            parent_span_id: 'a7b3c4d5e6f7a8b9',
            name: 'DELETE FROM sessions WHERE expires_at < NOW()',
            service_name: 'postgres',
            span_kind: 'client',
            status_code: 'error',
            status_message: 'too many clients already',
            offset_ms: 15,
            duration_ms: 490,
            attributes: { 'db.system': 'postgresql', 'db.name': 'sessions_db', 'db.operation': 'DELETE' },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
    ]),

    // 8: GET /api/dashboard — 6 spans, 340ms, OK
    makeTrace([
        makeSpan(t8, t8Base, {
            span_id: 'b8a2b3c4d5e6f7a8',
            name: 'GET /api/dashboard',
            service_name: 'web-app',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 340,
            attributes: { 'http.method': 'GET', 'http.route': '/api/dashboard', 'http.status_code': '200' },
            resource_extra: { 'service.version': '4.2.0' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t8, t8Base, {
            span_id: 'b8b3c4d5e6f7a8b9',
            parent_span_id: 'b8a2b3c4d5e6f7a8',
            name: 'verify-token',
            service_name: 'auth-service',
            span_kind: 'client',
            offset_ms: 3,
            duration_ms: 40,
            attributes: { 'rpc.system': 'grpc', 'rpc.method': 'VerifyToken' },
        }),
        makeSpan(t8, t8Base, {
            span_id: 'b8c4d5e6f7a8b9c0',
            parent_span_id: 'b8a2b3c4d5e6f7a8',
            name: 'get-analytics',
            service_name: 'analytics-service',
            span_kind: 'client',
            offset_ms: 48,
            duration_ms: 180,
            attributes: { 'analytics.metrics': 'pageviews,sessions,events', 'analytics.period': '7d' },
        }),
        makeSpan(t8, t8Base, {
            span_id: 'b8d5e6f7a8b9c0d1',
            parent_span_id: 'b8c4d5e6f7a8b9c0',
            name: 'SELECT count(*) FROM events GROUP BY date',
            service_name: 'clickhouse',
            span_kind: 'client',
            offset_ms: 55,
            duration_ms: 120,
            attributes: { 'db.system': 'clickhouse', 'db.name': 'posthog', 'db.rows_read': '1500000' },
        }),
        makeSpan(t8, t8Base, {
            span_id: 'b8e6f7a8b9c0d1e2',
            parent_span_id: 'b8a2b3c4d5e6f7a8',
            name: 'get-recent-activity',
            service_name: 'activity-service',
            span_kind: 'client',
            offset_ms: 235,
            duration_ms: 95,
            attributes: { 'activity.limit': '10' },
        }),
        makeSpan(t8, t8Base, {
            span_id: 'b8f7a8b9c0d1e2f3',
            parent_span_id: 'b8e6f7a8b9c0d1e2',
            name: 'SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 10',
            service_name: 'postgres',
            span_kind: 'client',
            offset_ms: 240,
            duration_ms: 55,
            attributes: { 'db.system': 'postgresql', 'db.name': 'activity_db', 'db.operation': 'SELECT' },
            instrumentation_scope: '@opentelemetry/instrumentation-pg@0.38.0',
        }),
    ]),

    // 9: POST /webhooks/stripe — 3 spans, 67ms, OK
    makeTrace([
        makeSpan(t9, t9Base, {
            span_id: 'c9a2b3c4d5e6f7a8',
            name: 'POST /webhooks/stripe',
            service_name: 'webhook-receiver',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 67,
            attributes: {
                'http.method': 'POST',
                'http.route': '/webhooks/stripe',
                'http.status_code': '200',
                'webhook.type': 'payment_intent.succeeded',
            },
            resource_extra: { 'service.version': '1.1.0' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t9, t9Base, {
            span_id: 'c9b3c4d5e6f7a8b9',
            parent_span_id: 'c9a2b3c4d5e6f7a8',
            name: 'update-order-status',
            service_name: 'order-service',
            span_kind: 'client',
            offset_ms: 10,
            duration_ms: 45,
            attributes: {
                'rpc.system': 'grpc',
                'rpc.method': 'UpdateOrderStatus',
                'order.id': 'ord_98765',
                'order.status': 'paid',
            },
        }),
        makeSpan(t9, t9Base, {
            span_id: 'c9c4d5e6f7a8b9c0',
            parent_span_id: 'c9a2b3c4d5e6f7a8',
            name: 'publish order.paid',
            service_name: 'kafka-producer',
            span_kind: 'producer',
            offset_ms: 58,
            duration_ms: 5,
            attributes: {
                'messaging.system': 'kafka',
                'messaging.destination': 'order.events',
                'messaging.operation': 'publish',
            },
            instrumentation_scope: '@opentelemetry/instrumentation-kafkajs@0.1.0',
        }),
    ]),

    // 10: GET /api/feature-flags — 2 spans, 8ms, OK (very fast, cache hit)
    makeTrace([
        makeSpan(t10, t10Base, {
            span_id: 'd0a2b3c4d5e6f7a8',
            name: 'GET /api/feature-flags',
            service_name: 'api-gateway',
            span_kind: 'server',
            offset_ms: 0,
            duration_ms: 8,
            attributes: { 'http.method': 'GET', 'http.route': '/api/feature-flags', 'http.status_code': '200' },
            resource_extra: { 'service.version': '2.4.1' },
            instrumentation_scope: '@opentelemetry/instrumentation-http@0.41.0',
        }),
        makeSpan(t10, t10Base, {
            span_id: 'd0b3c4d5e6f7a8b9',
            parent_span_id: 'd0a2b3c4d5e6f7a8',
            name: 'GET flags:team_123',
            service_name: 'redis',
            span_kind: 'client',
            offset_ms: 1,
            duration_ms: 2,
            attributes: { 'db.system': 'redis', 'db.operation': 'GET', 'cache.hit': 'true', 'flags.count': '12' },
            instrumentation_scope: '@opentelemetry/instrumentation-redis@0.38.0',
        }),
    ]),
]

export const MOCK_SPARKLINE_DATA = {
    labels: Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`),
    series: [
        {
            name: 'ok',
            values: [
                45, 52, 38, 28, 15, 12, 18, 42, 85, 120, 145, 132, 128, 140, 155, 148, 135, 110, 95, 78, 65, 58, 50, 48,
            ],
            color: 'success',
        },
        {
            name: 'error',
            values: [2, 1, 0, 1, 0, 0, 1, 3, 5, 8, 12, 6, 4, 7, 9, 5, 3, 4, 2, 3, 1, 2, 1, 0],
            color: 'danger',
        },
    ],
}

export const MOCK_SERVICES = [
    'api-gateway',
    'web-app',
    'auth-service',
    'user-service',
    'payment-service',
    'cart-service',
    'inventory-service',
    'search-service',
    'notification-service',
    'analytics-service',
    'postgres',
    'redis',
    'clickhouse',
    'kafka-producer',
]
