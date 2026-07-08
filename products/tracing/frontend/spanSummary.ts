// Derive the adaptive span-summary header (JON-37) from a span's native fields + well-known OTel
// attributes. Every field is optional in the output where the data is — the header renders only
// what resolves and reflows, so a bare internal span shows little and an HTTP-to-k8s span lights up.

import type { Span } from './types'
import { SPAN_KIND_LABELS, STATUS_CODE_LABELS } from './types'

export type SummaryStatusType = 'success' | 'warning' | 'danger' | 'default'

export interface SpanSummary {
    /** http method+route if present, else the span name. */
    operation: string
    /** http status (colored by class) if present, else the OTel status. */
    status: { label: string; type: SummaryStatusType }
    service: string
    /** Callee, if a peer attribute is set — drives the "service → peer" arrow. */
    peerService: string | null
    durationNano: number
    spanId: string
    traceId: string
    /** Empty for a root span — the header renders the parent link only when set. */
    parentSpanId: string | null
    /** OTel span kind label (Internal / Server / Client / Producer / Consumer). */
    kind: string
    timestamp: string
    endTimestamp: string
    /** HTTP / Database / RPC / Messaging, derived from the attribute namespace; null if unknown. */
    type: string | null
    cluster: string | null
    pod: string | null
}

// new and old semantic-convention spellings, tried in order.
const METHOD_KEYS = ['http.request.method', 'http.method']
const ROUTE_KEYS = ['http.route', 'http.target', 'url.path']
const HTTP_STATUS_KEYS = ['http.response.status_code', 'http.status_code']
// Logical service-identity attributes only — NOT transport-layer addresses like `server.address`
// (a host/IP that any DB/Redis/gRPC client span carries), which would render a misleading
// "service → 10.0.0.5:5432" peer arrow.
const PEER_KEYS = ['peer.service', 'net.peer.name']

function firstAttr(attrs: Record<string, string>, keys: string[]): string | null {
    for (const key of keys) {
        if (attrs[key]) {
            return attrs[key]
        }
    }
    return null
}

function httpStatusType(code: number): SummaryStatusType {
    if (code >= 500) {
        return 'danger'
    }
    if (code >= 400) {
        return 'warning'
    }
    if (code >= 200 && code < 300) {
        return 'success'
    }
    return 'default'
}

function deriveType(attrs: Record<string, string>): string | null {
    for (const key of Object.keys(attrs)) {
        if (key.startsWith('http.') || key.startsWith('url.')) {
            return 'HTTP'
        }
        if (key.startsWith('db.')) {
            return 'Database'
        }
        if (key.startsWith('rpc.')) {
            return 'RPC'
        }
        if (key.startsWith('messaging.')) {
            return 'Messaging'
        }
    }
    return null
}

// The query text for a DB span. `db.query.text` is the stabilized OTel DB-semconv key; `db.statement`
// is the long-standing (pre-rename) spelling most deployed instrumentations still emit — check both.
// Usually parameterized (literal values stripped to `?`) by the instrumentation. Null for non-DB spans.
export function getQueryText(span: Span): string | null {
    return firstAttr(span.attributes ?? {}, ['db.query.text', 'db.statement'])
}

export function deriveSpanSummary(span: Span): SpanSummary {
    const attrs = span.attributes ?? {}
    const resourceAttrs = span.resource_attributes ?? {}

    const method = firstAttr(attrs, METHOD_KEYS)
    const route = firstAttr(attrs, ROUTE_KEYS)
    const operation = method ? `${method} ${route ?? ''}`.trim() : span.name

    const httpStatus = firstAttr(attrs, HTTP_STATUS_KEYS)
    let status: { label: string; type: SummaryStatusType }
    if (httpStatus) {
        const code = parseInt(httpStatus, 10)
        status = { label: httpStatus, type: Number.isNaN(code) ? 'default' : httpStatusType(code) }
    } else {
        status = STATUS_CODE_LABELS[span.status_code] ?? { label: String(span.status_code), type: 'default' }
    }

    return {
        operation,
        status,
        service: span.service_name,
        peerService: firstAttr(attrs, PEER_KEYS),
        durationNano: span.duration_nano,
        spanId: span.span_id,
        traceId: span.trace_id,
        parentSpanId: span.parent_span_id || null,
        kind: SPAN_KIND_LABELS[span.kind] ?? String(span.kind),
        timestamp: span.timestamp,
        endTimestamp: span.end_time,
        type: deriveType(attrs),
        // k8s.* are OTel *resource* attributes, so read the resource map first; fall back to span
        // attributes for collectors that flatten them in. Absent in both → no chip.
        cluster: resourceAttrs['k8s.cluster.name'] || attrs['k8s.cluster.name'] || null,
        pod: resourceAttrs['k8s.pod.name'] || attrs['k8s.pod.name'] || null,
    }
}
