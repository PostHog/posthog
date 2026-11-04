// Run from the repository root: cd nodejs && npx tsx --tsconfig tsconfig.json ../rust/logs-ingestion/scripts/node-metric-rules-reference.ts
import { createHmac } from 'crypto'
import { writeFileSync } from 'fs'
import { join } from 'path'

import { type MetricRuleRow, compileMetricRules } from '../../../nodejs/src/logs/metrics-rules/compile-metric-rules'
import { withDefaultMetricRules } from '../../../nodejs/src/logs/metrics-rules/default-metric-rules'
import { buildMetricRulesOtlpPayload } from '../../../nodejs/src/logs/metrics-rules/otlp-payload'
import {
    MetricSeriesAdmission,
    createBatchTallies,
    idToHex,
    tallyRecords,
} from '../../../nodejs/src/logs/metrics-rules/tally'

const NOW_MS = Date.UTC(2025, 0, 15, 12, 37, 13, 250)
const HOUR_MS = 60 * 60 * 1000

const rules = compileMetricRules([
    { id: 'r', metric_name: 'm', filter_group: null, value_attribute: null, group_by: ['attributes.v'] },
])
const rocket = '🚀'
const labelValues: string[] = [
    'x'.repeat(256),
    'x'.repeat(257),
    'x'.repeat(255) + rocket,
    'x'.repeat(254) + rocket,
    'x'.repeat(254) + rocket + 'y',
    rocket.repeat(128),
    rocket.repeat(129),
    'a' + rocket.repeat(200),
    'é'.repeat(300),
    '日本'.repeat(200),
    '\ud83d'.repeat(300),
    'x'.repeat(255) + '\udc00z',
]
const labelInputs: string[] = [...labelValues.map((v) => JSON.stringify(v)), 'raw-' + rocket.repeat(200)]
const labels = labelInputs.map((attribute) => {
    const tallies = createBatchTallies()
    const record = { timestamp: null, trace_id: null, span_id: null, attributes: { v: attribute } }
    tallyRecords(rules, [record as never], tallies, NOW_MS)
    const [[labelKey, entry]] = [...tallies.byRule.get('r')!.entries()]
    return { attribute, length: entry.labelValues[0].length, label_key: labelKey }
})

const b64 = (bytes: number[]): string => Buffer.from(bytes).toString('base64')
const trace = Array.from({ length: 16 }, (_, i) => i * 17 + 1)
const span = Array.from({ length: 8 }, (_, i) => 255 - i)
const ascii = (s: string): Buffer => Buffer.from(s, 'latin1')
const idInputs: [Buffer, number][] = [
    [Buffer.from(trace), 16],
    [Buffer.from(span), 8],
    [Buffer.alloc(16), 16],
    [Buffer.alloc(0), 16],
    [ascii(b64(trace)), 16],
    [ascii(b64(trace).replace(/=+$/, '')), 16],
    [ascii(b64(span)), 8],
    [ascii(b64(span).replace(/\+/g, '-').replace(/\//g, '_')), 8],
    [ascii(' ' + b64(trace).slice(0, 10) + '\n*' + b64(trace).slice(10)), 16],
    [ascii(b64(trace).slice(0, 8) + '=' + b64(trace).slice(8)), 16],
    [ascii(b64(Array(16).fill(0))), 16],
    [ascii(b64(trace) + 'AAAA'), 16],
    [Buffer.from(b64(trace), 'latin1').map((b) => b | 0x80), 16],
    [ascii(b64(Array.from({ length: 15 }, (_, i) => i + 1))), 16],
    [ascii('not base64 at all!!'), 16],
    [Buffer.from(trace.slice(0, 15)), 16],
]
const id_to_hex = idInputs.map(([buffer, expectedBytes]) => ({
    input_hex: buffer.toString('hex'),
    expected_bytes: expectedBytes,
    output: idToHex(buffer.length ? buffer : null, expectedBytes),
}))

// hashLabelKey keeps its key private, so this repeats its one line with a fixed key.
const hmacKey = Buffer.from(Array.from({ length: 32 }, (_, i) => (i * 37 + 11) & 0xff))
const label_hashes = ['[]', '[""]', '["api","ERROR"]', JSON.stringify(['\ud83d' + 'x']), JSON.stringify([rocket.repeat(3)])].map(
    (labelKey) => ({
        label_key: labelKey,
        hash: createHmac('sha256', hmacKey).update(labelKey).digest().readUIntBE(0, 6),
    })
)

type Call = [number, string, string, number]
const scenario = (name: string, caps: [number, number, number], calls: Call[]) => {
    const admission = new MetricSeriesAdmission(...caps)
    return { name, caps, calls, results: calls.map((c) => admission.admit(...c)) }
}
const t0 = Math.floor(NOW_MS / HOUR_MS) * HOUR_MS
const admission = [
    scenario('per rule cap', [2, 10, 100], [
        [1, 'r', '["a"]', NOW_MS],
        [1, 'r', '["b"]', NOW_MS],
        [1, 'r', '["c"]', NOW_MS],
        [1, 'r', '["a"]', NOW_MS],
        [1, 'r2', '["c"]', NOW_MS],
        [2, 'r', '["c"]', NOW_MS],
    ]),
    scenario('per team cap survives other rules', [10, 3, 100], [
        [1, 'r1', '["a"]', NOW_MS],
        [1, 'r2', '["a"]', NOW_MS],
        [1, 'r3', '["a"]', NOW_MS],
        [1, 'r4', '["a"]', NOW_MS],
        [1, 'r1', '["a"]', NOW_MS],
        [2, 'r1', '["a"]', NOW_MS],
    ]),
    scenario('total cap', [10, 10, 2], [
        [1, 'r', '["a"]', NOW_MS],
        [2, 'r', '["a"]', NOW_MS],
        [3, 'r', '["a"]', NOW_MS],
        [1, 'r', '["a"]', NOW_MS],
    ]),
    scenario('window rollover', [1, 1, 1], [
        [1, 'r', '["a"]', t0 + HOUR_MS - 1],
        [1, 'r', '["b"]', t0 + HOUR_MS - 1],
        [1, 'r', '["b"]', t0 + HOUR_MS],
        [1, 'r', '["a"]', t0 + HOUR_MS + 1],
        [1, 'r', '["a"]', t0 + 1.5],
        [1, 'r', '["a"]', t0 + 2],
        [1, 'r', '["b"]', t0 + 2 * HOUR_MS + 0.25],
    ]),
    scenario('team and rule ids share a key space', [1, 10, 100], [
        [1, '2:r', '["a"]', NOW_MS],
        [12, 'r', '["a"]', NOW_MS],
        [1, '2:r', '["b"]', NOW_MS],
    ]),
]

// The module vectors cover none of these, because their value attributes never resolve.
const spanRecord = (i: number, extra: Record<string, unknown>): Record<string, unknown> => ({
    uuid: `s${i}`,
    trace_id: i % 3 === 0 ? null : Buffer.from(Array.from({ length: 16 }, (_, j) => (i * 31 + j) & 0xff)),
    span_id: i % 2 === 0 ? null : Buffer.from(Array.from({ length: 8 }, (_, j) => (i + j) & 0xff)),
    timestamp: (NOW_MS - 1000 * i) * 1000,
    end_time: (NOW_MS - 1000 * i) * 1000 + [1500, 0, 7_250_125, 250, 12_000_000_001][i % 5],
    name: ['GET /a', 'db.query', 'x'.repeat(300), ''][i % 4],
    kind: [1, 2, 3, 9, null][i % 5],
    status_code: [0, 1, 2, 7, null][i % 5],
    service_name: ['api', 'worker', null][i % 3],
    resource_attributes: { 'k8s.pod.name': JSON.stringify(`pod-${i % 2}`) },
    attributes: { ms: JSON.stringify([12.5, '  3e2ms', 'x', -4, 'Infinity', 0.1, '1e400'][i % 7]), 'http.method': '"GET"' },
    ...extra,
})
const logRecord = (i: number, extra: Record<string, unknown>): Record<string, unknown> => ({
    uuid: `l${i}`,
    trace_id: [null, Buffer.from(b64(trace), 'latin1'), Buffer.alloc(16)][i % 3],
    span_id: Buffer.from(span),
    timestamp: [null, (NOW_MS - 60_000) * 1000, (NOW_MS - 21 * 60_000) * 1000][i % 3],
    service_name: ['api', 'web'][i % 2],
    severity_text: ['INFO', 'ERROR', null][i % 3],
    event_name: null,
    attributes: { ms: JSON.stringify(i * 997.5), user: JSON.stringify(i % 4 === 0 ? 'deny' : `u${i % 5}`) },
    resource_attributes: null,
    ...extra,
})
const recordJson = (record: Record<string, unknown>): unknown =>
    Object.fromEntries(
        Object.entries(record).map(([k, v]) => [k, Buffer.isBuffer(v) ? { $bytes: v.toString('hex') } : v])
    )
type PayloadCase = { rows: MetricRuleRow[]; defaults: 'logs' | 'spans' | null; records: Record<string, unknown>[] }
const payloadCases: PayloadCase[] = [
    {
        rows: [
            { id: 'd', metric_name: 'span.ms', source: 'spans', filter_group: null, value_attribute: 'duration_ms', group_by: ['service_name', 'kind', 'name', 'status_code'] },
            { id: 'h', metric_name: 'span.attr', source: 'spans', filter_group: null, value_attribute: 'attributes.ms', group_by: ['resource_attributes.k8s.pod.name', 'attributes.http.method'] },
            { id: 'c', metric_name: 'span.count', source: 'spans', filter_group: null, value_attribute: null, group_by: [] },
        ],
        defaults: null,
        records: Array.from({ length: 20 }, (_, i) => spanRecord(i, {})),
    },
    {
        rows: [
            { id: 'u', metric_name: 'by.user', filter_group: null, value_attribute: null, group_by: ['service_name', 'attributes.user', 'severity_text'] },
            { id: 'v', metric_name: 'posthog.log.records', filter_group: null, value_attribute: 'attributes.ms', group_by: ['attributes.user'] },
            { id: 'u', metric_name: 'same.id', filter_group: null, value_attribute: null, group_by: ['event_name'] },
        ],
        defaults: 'logs',
        records: Array.from({ length: 24 }, (_, i) => logRecord(i, {})),
    },
    {
        rows: [{ id: 'n', metric_name: 'none', filter_group: null, value_attribute: 'attributes.missing', group_by: [] }],
        defaults: null,
        records: Array.from({ length: 3 }, (_, i) => logRecord(i, {})),
    },
    {
        // Attribute maps are plain objects, so these keys read Object.prototype members.
        rows: [
            { id: 'p', metric_name: 'proto', filter_group: null, value_attribute: 'attributes.valueOf', group_by: [] },
            { id: 'q', metric_name: 'proto.labels', filter_group: null, value_attribute: null, group_by: ['attributes.constructor', 'attributes.__proto__', 'attributes.toString', 'resource_attributes.__proto__'] },
        ],
        defaults: null,
        records: Array.from({ length: 4 }, (_, i) => logRecord(i, { resource_attributes: i % 2 ? { a: '"b"' } : null })),
    },
    {
        // `__defineGetter__.length` is 2, so decodeLogAttributeValue calls a missing startsWith and throws.
        rows: [
            { id: 'ok', metric_name: 'ok', filter_group: null, value_attribute: null, group_by: [] },
            { id: 't', metric_name: 'throws', filter_group: null, value_attribute: null, group_by: ['attributes.__defineGetter__'] },
        ],
        defaults: null,
        records: Array.from({ length: 3 }, (_, i) => logRecord(i * 3 + 1, {})),
    },
    {
        rows: [],
        defaults: 'spans',
        records: Array.from({ length: 10 }, (_, i) => spanRecord(i, {})),
    },
]
const payloads = payloadCases.map(({ rows, defaults, records }) => {
    let compiled = compileMetricRules(rows)
    if (defaults) {
        compiled = withDefaultMetricRules(compiled, defaults)
    }
    const tallies = createBatchTallies()
    let threw: string | null = null
    try {
        tallyRecords(compiled, records as never[], tallies, NOW_MS, (_ruleId, labelKey) => !labelKey.includes('deny'))
    } catch (error) {
        threw = String(error)
    }
    const payload = buildMetricRulesOtlpPayload(compiled, tallies, NOW_MS)
    return {
        rows,
        defaults,
        now_ms: NOW_MS,
        records: records.map(recordJson),
        payload_json: payload === null ? null : JSON.stringify(payload),
        value_skipped: tallies.valueSkipped,
        eval_errors: tallies.evalErrors,
        series_overflow: Object.fromEntries(tallies.seriesOverflow),
        threw,
    }
})

const compileRows = [
    { id: 'a', metric_name: '', filter_group: null, value_attribute: null, group_by: [] },
    { id: 'b', metric_name: 5, filter_group: null, value_attribute: null, group_by: [] },
    { id: 'c', filter_group: null, value_attribute: null, group_by: [] },
    { id: 'd', metric_name: 'd', source: 'SPANS', value_attribute: '', group_by: ['severity_text', 1, '', null, 'event_name'] },
    { id: 'e', metric_name: 'e', source: 'spans', value_attribute: 'duration_ms', group_by: ['kind', 'name', 'status_code', 'service_name', 'attributes.a', 'attributes.b'] },
    { id: 'f', metric_name: 'f', source: 'spans', value_attribute: 7, group_by: ['severity_text'] },
    { id: 'g', metric_name: 'g', value_attribute: 'x', group_by: ['name'] },
    { id: 'h', metric_name: 'h', value_attribute: 'duration_ms', group_by: [] },
    { id: 'i', metric_name: 'i', value_attribute: 'attributes.\ud800', group_by: ['resource_attributes.\udc00', 'attributes.'] },
    { id: 'j', metric_name: 'j', filter_group: undefined, value_attribute: null, group_by: 'service_name' },
    { id: 'k', metric_name: 'k', source: 'spans', value_attribute: null, group_by: ['event_name'] },
]
const compile = compileMetricRules(compileRows as unknown as MetricRuleRow[]).map((r) => ({
    id: r.id,
    metric_name: r.metricName,
    source: r.source,
    value_attribute: r.valueAttribute,
    group_by: r.groupBy,
}))

const out = { compile_rows: compileRows, compile, hmac_key_hex: hmacKey.toString('hex'), labels, id_to_hex, label_hashes, admission, payloads }
writeFileSync(
    join(__dirname, '..', 'tests', 'fixtures', 'metric-rules-reference.json'),
    JSON.stringify(out, null, 1) + '\n'
)
