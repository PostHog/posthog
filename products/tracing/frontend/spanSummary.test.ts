import { deriveSpanSummary, getQueryText } from './spanSummary'
import type { Span } from './types'

function makeSpan(overrides: Partial<Span>): Span {
    return {
        uuid: 'u',
        trace_id: 'trace-1',
        span_id: 'span-1',
        parent_span_id: '',
        name: 'internal-work',
        kind: 1,
        service_name: 'load-generator',
        status_code: 0,
        timestamp: '2026-06-11T10:45:47.752Z',
        end_time: '2026-06-11T10:45:47.762Z',
        duration_nano: 10_500_000,
        is_root_span: false,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

describe('deriveSpanSummary', () => {
    it('falls back to native fields for a bare internal span', () => {
        const s = deriveSpanSummary(makeSpan({}))
        expect(s.operation).toBe('internal-work')
        expect(s.status).toEqual({ label: 'OK', type: 'success' })
        expect(s.service).toBe('load-generator')
        expect(s.peerService).toBeNull()
        expect(s.type).toBeNull()
        expect(s.cluster).toBeNull()
        expect(s.pod).toBeNull()
        expect(s.parentSpanId).toBeNull()
        expect(s.kind).toBe('Internal')
    })

    it('carries the correlation IDs, kind, and end time the header surfaces', () => {
        const s = deriveSpanSummary(makeSpan({ parent_span_id: 'span-0', kind: 2 }))
        expect(s.spanId).toBe('span-1')
        expect(s.traceId).toBe('trace-1')
        expect(s.parentSpanId).toBe('span-0')
        expect(s.kind).toBe('Server')
        expect(s.endTimestamp).toBe('2026-06-11T10:45:47.762Z')
    })

    it('lights up an HTTP client span to a k8s peer', () => {
        const s = deriveSpanSummary(
            makeSpan({
                attributes: {
                    'http.request.method': 'GET',
                    'http.route': '/api/cart',
                    'http.response.status_code': '200',
                    'peer.service': 'frontend-proxy',
                    'k8s.cluster.name': 'k8s-demo',
                    'k8s.pod.name': 'load-generator-59f4b49995-w585b',
                },
            })
        )
        expect(s.operation).toBe('GET /api/cart')
        expect(s.status).toEqual({ label: '200', type: 'success' })
        expect(s.peerService).toBe('frontend-proxy')
        expect(s.type).toBe('HTTP')
        expect(s.cluster).toBe('k8s-demo')
        expect(s.pod).toBe('load-generator-59f4b49995-w585b')
    })

    it('reads k8s chips from resource attributes (their OTel home)', () => {
        const s = deriveSpanSummary(
            makeSpan({
                resource_attributes: { 'k8s.cluster.name': 'prod-eu', 'k8s.pod.name': 'web-abc12' },
            })
        )
        expect(s.cluster).toBe('prod-eu')
        expect(s.pod).toBe('web-abc12')
    })

    it('prefers resource-attribute k8s chips over span attributes when both are set', () => {
        const s = deriveSpanSummary(
            makeSpan({
                attributes: { 'k8s.cluster.name': 'span-cluster', 'k8s.pod.name': 'span-pod' },
                resource_attributes: { 'k8s.cluster.name': 'resource-cluster', 'k8s.pod.name': 'resource-pod' },
            })
        )
        expect(s.cluster).toBe('resource-cluster')
        expect(s.pod).toBe('resource-pod')
    })

    it.each([
        ['500', 'danger'],
        ['404', 'warning'],
        ['301', 'default'],
        ['204', 'success'],
    ])('colors http status %s as %s', (code, type) => {
        const s = deriveSpanSummary(makeSpan({ attributes: { 'http.status_code': code } }))
        expect(s.status).toEqual({ label: code, type })
    })

    it('accepts the old semconv method key and an absent route', () => {
        const s = deriveSpanSummary(makeSpan({ attributes: { 'http.method': 'POST' } }))
        expect(s.operation).toBe('POST')
        expect(s.type).toBe('HTTP')
    })

    it('uses the OTel status when there is no http status', () => {
        expect(deriveSpanSummary(makeSpan({ status_code: 2 })).status).toEqual({ label: 'Error', type: 'danger' })
    })

    it.each([
        [{ 'db.system': 'postgres' }, 'Database'],
        [{ 'rpc.method': 'GetCart' }, 'RPC'],
        [{ 'messaging.system': 'kafka' }, 'Messaging'],
    ])('derives type from the attribute namespace (%j)', (attributes, type) => {
        expect(deriveSpanSummary(makeSpan({ attributes })).type).toBe(type)
    })
})

describe('getQueryText', () => {
    it.each([
        // legacy spelling
        [{ 'db.statement': 'SELECT * FROM users WHERE id = ?' }, 'SELECT * FROM users WHERE id = ?'],
        // both present: the stabilized db.query.text wins over the legacy db.statement
        [{ 'db.query.text': 'SELECT 1', 'db.statement': 'SELECT 2' }, 'SELECT 1'],
        // non-DB span
        [{ 'http.method': 'GET' }, null],
    ])('resolves the DB query text from %j', (attributes, expected) => {
        expect(getQueryText(makeSpan({ attributes }))).toBe(expected)
    })
})
