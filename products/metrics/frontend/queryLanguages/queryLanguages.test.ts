import fs from 'fs'
import path from 'path'

import { NodeKind } from '~/queries/schema/schema-general'
import type { MetricsQuery } from '~/queries/schema/schema-general'

import { builderToPromql } from './builderToPromql'
import { builderToSql } from './builderToSql'
import { GENERIC_LOSS_ISSUE, canonicalBuilder, canonicalPromQL, convertMetricsQuery } from './convert'
import { PromQLParseError, parsePromQL } from './promqlParser'
import { printPromQL } from './promqlPrinter'
import { promqlToBuilder } from './promqlToBuilder'
import { builderRegexToPromRegex, promRegexToBuilderRegex } from './regex'
import { sqlToBuilder } from './sqlToBuilder'
import type { BuilderClause, BuilderQuery } from './types'

const clause = (fields: Partial<BuilderClause> & Pick<BuilderClause, 'metricName'>): BuilderClause => ({
    name: 'a',
    aggregation: 'sum',
    ...fields,
})

// Builder queries that every language can hold exactly. Each one must survive builder → PromQL → builder
// and builder → SQL → builder without a reported issue.
export const LOSSLESS_BUILDER_FIXTURES: Record<string, BuilderQuery> = {
    'gauge sum': { clauses: [clause({ metricName: 'queue_depth' })] },
    'gauge avg': { clauses: [clause({ metricName: 'process.cpu.utilization', aggregation: 'avg' })] },
    'gauge min': { clauses: [clause({ metricName: 'free_disk_bytes', aggregation: 'min' })] },
    'gauge max': { clauses: [clause({ metricName: 'jvm.memory.used', aggregation: 'max' })] },
    'series count': { clauses: [clause({ metricName: 'up', aggregation: 'count' })] },
    p95: { clauses: [clause({ metricName: 'request_latency_ms', aggregation: 'quantile', quantile: 0.95 })] },
    'counter rate': { clauses: [clause({ metricName: 'http.server.request.count', aggregation: 'rate' })] },
    'counter increase': { clauses: [clause({ metricName: 'jobs_processed_total', aggregation: 'increase' })] },
    'histogram p99': {
        clauses: [clause({ metricName: 'http.server.duration', aggregation: 'histogram_quantile', quantile: 0.99 })],
    },
    'histogram p50 by service': {
        clauses: [
            clause({
                metricName: 'http.server.duration',
                aggregation: 'histogram_quantile',
                quantile: 0.5,
                groupBy: [{ key: 'service_name' }],
            }),
        ],
    },
    'eq filter': {
        clauses: [clause({ metricName: 'queue_depth', filters: [{ key: 'service_name', op: 'eq', value: 'api' }] })],
    },
    'neq filter on dotted key': {
        clauses: [
            clause({
                metricName: 'http.server.request.count',
                aggregation: 'rate',
                filters: [{ key: 'http.request.method', op: 'neq', value: 'OPTIONS' }],
            }),
        ],
    },
    'multi-value chip regex': {
        clauses: [
            clause({
                metricName: 'queue_depth',
                filters: [{ key: 'service_name', op: 'regex', value: '^(?:api|worker)$' }],
            }),
        ],
    },
    'unanchored regex': {
        clauses: [clause({ metricName: 'queue_depth', filters: [{ key: 'http.route', op: 'regex', value: 'users' }] })],
    },
    'prefix regex': {
        clauses: [clause({ metricName: 'queue_depth', filters: [{ key: 'http.route', op: 'regex', value: '^/api' }] })],
    },
    'suffix not regex': {
        clauses: [
            clause({ metricName: 'queue_depth', filters: [{ key: 'http.route', op: 'not_regex', value: 'health$' }] }),
        ],
    },
    'empty service pattern': {
        clauses: [clause({ metricName: 'queue_depth', filters: [{ key: 'service_name', op: 'regex', value: '^$' }] })],
    },
    'value with quotes and backslashes': {
        clauses: [
            clause({
                metricName: 'queue_depth',
                filters: [{ key: 'queue', op: 'eq', value: `it's a "quoted" \\ value` }],
            }),
        ],
    },
    'several filters': {
        clauses: [
            clause({
                metricName: 'http.server.request.count',
                aggregation: 'increase',
                filters: [
                    { key: 'service_name', op: 'eq', value: 'api' },
                    { key: 'http.response.status_code', op: 'regex', value: '^5' },
                    { key: 'http.route', op: 'neq', value: '/health' },
                ],
            }),
        ],
    },
    'regex with an escaped dot': {
        clauses: [
            clause({
                metricName: 'build_info',
                aggregation: 'count',
                filters: [{ key: 'version', op: 'regex', value: '^v1\\.2' }],
            }),
        ],
    },
    'non-ASCII and spaced names': {
        clauses: [
            clause({
                metricName: 'größe_bytes',
                filters: [{ key: 'queue name', op: 'eq', value: 'é' }],
                groupBy: [{ key: 'région' }],
            }),
        ],
    },
    'group by one': { clauses: [clause({ metricName: 'queue_depth', groupBy: [{ key: 'service_name' }] })] },
    'group by two dotted': {
        clauses: [
            clause({
                metricName: 'http.server.request.count',
                aggregation: 'rate',
                groupBy: [{ key: 'http.route' }, { key: 'http.request.method' }],
            }),
        ],
    },
    'error ratio formula': {
        clauses: [
            clause({
                name: 'a',
                metricName: 'http.server.request.count',
                aggregation: 'rate',
                filters: [{ key: 'http.response.status_code', op: 'regex', value: '^5' }],
            }),
            clause({ name: 'b', metricName: 'http.server.request.count', aggregation: 'rate' }),
        ],
        formula: 'a / b * 100',
    },
    'parenthesized formula': {
        clauses: [
            clause({ name: 'a', metricName: 'queue_depth' }),
            clause({ name: 'b', metricName: 'retry_queue_depth' }),
        ],
        formula: '(a + b) / 2',
    },
    'grouped formula with the same labels': {
        clauses: [
            clause({
                name: 'a',
                metricName: 'errors_total',
                aggregation: 'increase',
                groupBy: [{ key: 'service_name' }],
            }),
            clause({
                name: 'b',
                metricName: 'requests_total',
                aggregation: 'increase',
                groupBy: [{ key: 'service_name' }],
            }),
        ],
        formula: 'a / b',
    },
    'right-nested formula': {
        clauses: [
            clause({ name: 'a', metricName: 'queue_depth' }),
            clause({ name: 'b', metricName: 'retry_queue_depth' }),
            clause({ name: 'c', metricName: 'dead_queue_depth' }),
        ],
        formula: 'a - (b - c)',
    },
    'unary minus formula': {
        clauses: [clause({ name: 'a', metricName: 'queue_depth' })],
        formula: '-a',
    },
    'two series without formula': {
        clauses: [
            clause({ name: 'a', metricName: 'queue_depth' }),
            clause({ name: 'b', metricName: 'process.cpu.utilization', aggregation: 'avg' }),
        ],
    },
    'three series with groups': {
        clauses: [
            clause({ name: 'a', metricName: 'queue_depth', groupBy: [{ key: 'service_name' }] }),
            clause({ name: 'b', metricName: 'http.server.request.count', aggregation: 'rate' }),
            clause({ name: 'c', metricName: 'up', aggregation: 'count', groupBy: [{ key: 'service_name' }] }),
        ],
    },
}

const PROMQL_CASES: [string, BuilderQuery | null, 'lossless' | 'lossy'][] = [
    ['sum(queue_depth)', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossless'],
    [
        'sum(queue_depth) by (service_name)',
        { clauses: [clause({ metricName: 'queue_depth', groupBy: [{ key: 'service_name' }] })] },
        'lossless',
    ],
    [
        'avg by (service_name) (process_cpu_usage)',
        {
            clauses: [
                clause({ metricName: 'process_cpu_usage', aggregation: 'avg', groupBy: [{ key: 'service_name' }] }),
            ],
        },
        'lossless',
    ],
    [
        'max(jvm_memory_used_bytes{area="heap"})',
        {
            clauses: [
                clause({
                    metricName: 'jvm_memory_used_bytes',
                    aggregation: 'max',
                    filters: [{ key: 'area', op: 'eq', value: 'heap' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'min(free_disk_bytes{mount!="/boot"})',
        {
            clauses: [
                clause({
                    metricName: 'free_disk_bytes',
                    aggregation: 'min',
                    filters: [{ key: 'mount', op: 'neq', value: '/boot' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'count(up{job=~"api.*"})',
        {
            clauses: [
                clause({
                    metricName: 'up',
                    aggregation: 'count',
                    filters: [{ key: 'job', op: 'regex', value: '^api' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'sum(queue_depth{queue!~"dead|retry"})',
        {
            clauses: [
                clause({
                    metricName: 'queue_depth',
                    filters: [{ key: 'queue', op: 'not_regex', value: '^(?:dead|retry)$' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'quantile(0.95, request_latency_ms)',
        { clauses: [clause({ metricName: 'request_latency_ms', aggregation: 'quantile', quantile: 0.95 })] },
        'lossless',
    ],
    [
        'quantile by (service_name) (0.95, request_latency_ms)',
        {
            clauses: [
                clause({
                    metricName: 'request_latency_ms',
                    aggregation: 'quantile',
                    quantile: 0.95,
                    groupBy: [{ key: 'service_name' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'sum(rate(http_requests_total))',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossless',
    ],
    [
        'sum(rate(http_requests_total[5m]))',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossy',
    ],
    [
        'sum(rate(http_requests_total[$__rate_interval])) by (job)',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate', groupBy: [{ key: 'job' }] })] },
        'lossless',
    ],
    [
        'sum(increase(jobs_total[1h]))',
        { clauses: [clause({ metricName: 'jobs_total', aggregation: 'increase' })] },
        'lossy',
    ],
    [
        'sum by (http.route) (rate({"http.server.request.count"}))',
        {
            clauses: [
                clause({
                    metricName: 'http.server.request.count',
                    aggregation: 'rate',
                    groupBy: [{ key: 'http.route' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'sum by ("http.route") (rate({"http.server.request.count", "http.request.method"="GET"}))',
        {
            clauses: [
                clause({
                    metricName: 'http.server.request.count',
                    aggregation: 'rate',
                    groupBy: [{ key: 'http.route' }],
                    filters: [{ key: 'http.request.method', op: 'eq', value: 'GET' }],
                }),
            ],
        },
        'lossless',
    ],
    ['sum(http.server.request.count)', { clauses: [clause({ metricName: 'http.server.request.count' })] }, 'lossless'],
    [
        "sum(queue_depth{queue='main', path=`C:\\tmp`})",
        {
            clauses: [
                clause({
                    metricName: 'queue_depth',
                    filters: [
                        { key: 'queue', op: 'eq', value: 'main' },
                        { key: 'path', op: 'eq', value: 'C:\\tmp' },
                    ],
                }),
            ],
        },
        'lossless',
    ],
    [
        'sum(queue_depth{queue="caf\\xc3\\xa9", region="\\u00e9u", zone="\\303\\251"})',
        {
            clauses: [
                clause({
                    metricName: 'queue_depth',
                    filters: [
                        { key: 'queue', op: 'eq', value: 'café' },
                        { key: 'region', op: 'eq', value: 'éu' },
                        { key: 'zone', op: 'eq', value: 'é' },
                    ],
                }),
            ],
        },
        'lossless',
    ],
    [
        'sum({__name__="queue_depth", queue="main"})',
        { clauses: [clause({ metricName: 'queue_depth', filters: [{ key: 'queue', op: 'eq', value: 'main' }] })] },
        'lossless',
    ],
    [
        'sum(rate(http_requests_total{service_name="api", http_route=~"/api/.*"}))',
        {
            clauses: [
                clause({
                    metricName: 'http_requests_total',
                    aggregation: 'rate',
                    filters: [
                        { key: 'service_name', op: 'eq', value: 'api' },
                        { key: 'http_route', op: 'regex', value: '^/api/' },
                    ],
                }),
            ],
        },
        'lossless',
    ],
    [
        'histogram_quantile(0.99, sum by (le) (rate(http_server_duration_bucket[5m])))',
        {
            clauses: [
                clause({ metricName: 'http_server_duration', aggregation: 'histogram_quantile', quantile: 0.99 }),
            ],
        },
        'lossy',
    ],
    [
        'histogram_quantile(0.5, sum by (le, service_name) (rate({"http.server.duration_bucket"})))',
        {
            clauses: [
                clause({
                    metricName: 'http.server.duration',
                    aggregation: 'histogram_quantile',
                    quantile: 0.5,
                    groupBy: [{ key: 'service_name' }],
                }),
            ],
        },
        'lossless',
    ],
    [
        'histogram_quantile(0.99, rate(latency_bucket))',
        { clauses: [clause({ metricName: 'latency', aggregation: 'histogram_quantile', quantile: 0.99 })] },
        'lossy',
    ],
    ['histogram_quantile(0.9, latency)', null, 'lossy'],
    [
        'histogram_quantile(0.9, sum(rate(latency_bucket)) by (le))',
        { clauses: [clause({ metricName: 'latency', aggregation: 'histogram_quantile', quantile: 0.9 })] },
        'lossless',
    ],
    [
        'sum(rate(errors_total)) / sum(rate(requests_total))',
        {
            clauses: [
                clause({ name: 'a', metricName: 'errors_total', aggregation: 'rate' }),
                clause({ name: 'b', metricName: 'requests_total', aggregation: 'rate' }),
            ],
            formula: 'a / b',
        },
        'lossless',
    ],
    [
        'sum(rate(errors_total)) / sum(rate(requests_total)) * 100',
        {
            clauses: [
                clause({ name: 'a', metricName: 'errors_total', aggregation: 'rate' }),
                clause({ name: 'b', metricName: 'requests_total', aggregation: 'rate' }),
            ],
            formula: 'a / b * 100',
        },
        'lossless',
    ],
    [
        '100 * (1 - sum(rate(errors_total)) / sum(rate(requests_total)))',
        {
            clauses: [
                clause({ name: 'a', metricName: 'errors_total', aggregation: 'rate' }),
                clause({ name: 'b', metricName: 'requests_total', aggregation: 'rate' }),
            ],
            formula: '100 * (1 - a / b)',
        },
        'lossless',
    ],
    [
        '(sum(queue_depth) + sum(retry_queue_depth)) / 2',
        {
            clauses: [
                clause({ name: 'a', metricName: 'queue_depth' }),
                clause({ name: 'b', metricName: 'retry_queue_depth' }),
            ],
            formula: '(a + b) / 2',
        },
        'lossless',
    ],
    ['-sum(queue_depth)', { clauses: [clause({ metricName: 'queue_depth' })], formula: '-a' }, 'lossless'],
    [
        'sum(queue_depth) - sum(queue_depth)',
        { clauses: [clause({ metricName: 'queue_depth' })], formula: 'a - a' },
        'lossless',
    ],
    [
        'sum by (job) (rate(errors_total)) / on() group_left sum(rate(requests_total))',
        {
            clauses: [
                clause({ name: 'a', metricName: 'errors_total', aggregation: 'rate', groupBy: [{ key: 'job' }] }),
                clause({ name: 'b', metricName: 'requests_total', aggregation: 'rate' }),
            ],
            formula: 'a / b',
        },
        'lossless',
    ],
    [
        'label_replace(sum(queue_depth), "clause", "a", "", "") or label_replace(avg(cpu), "clause", "b", "", "")',
        {
            clauses: [
                clause({ name: 'a', metricName: 'queue_depth' }),
                clause({ name: 'b', metricName: 'cpu', aggregation: 'avg' }),
            ],
        },
        'lossless',
    ],
    [
        'max by (instance) (fs_avail_bytes{mountpoint="/"} / fs_size_bytes{mountpoint="/"})',
        {
            clauses: [
                clause({
                    name: 'a',
                    metricName: 'fs_avail_bytes',
                    aggregation: 'max',
                    filters: [{ key: 'mountpoint', op: 'eq', value: '/' }],
                    groupBy: [{ key: 'instance' }],
                }),
                clause({
                    name: 'b',
                    metricName: 'fs_size_bytes',
                    aggregation: 'max',
                    filters: [{ key: 'mountpoint', op: 'eq', value: '/' }],
                    groupBy: [{ key: 'instance' }],
                }),
            ],
            formula: 'a / b',
        },
        'lossy',
    ],
    [
        'sum(queue_depth) or sum(retry_queue_depth)',
        {
            clauses: [
                clause({ name: 'a', metricName: 'queue_depth' }),
                clause({ name: 'b', metricName: 'retry_queue_depth' }),
            ],
        },
        'lossy',
    ],
    [
        'sum by (job) (rate(errors_total)) / ignoring(instance) sum by (job) (rate(requests_total))',
        {
            clauses: [
                clause({ name: 'a', metricName: 'errors_total', aggregation: 'rate', groupBy: [{ key: 'job' }] }),
                clause({ name: 'b', metricName: 'requests_total', aggregation: 'rate', groupBy: [{ key: 'job' }] }),
            ],
            formula: 'a / b',
        },
        'lossy',
    ],
    ['sum(errors_total) % sum(requests_total)', { clauses: [clause({ metricName: 'errors_total' })] }, 'lossy'],
    [
        'label_replace(sum(queue_depth), "queue_alias", "$1", "queue", "(.*)")',
        { clauses: [clause({ metricName: 'queue_depth' })] },
        'lossy',
    ],
    ['avg(sum by (job) (queue_depth))', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['sum(queue_depth) offset 1h', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['sum(queue_depth offset 1h)', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['sum(queue_depth) > 5', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    [
        'topk(5, sum by (queue) (queue_depth))',
        { clauses: [clause({ metricName: 'queue_depth', groupBy: [{ key: 'queue' }] })] },
        'lossy',
    ],
    ['sum without (instance) (queue_depth)', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['queue_depth', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    [
        'rate(http_requests_total[1m])',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossy',
    ],
    [
        'sum(irate(http_requests_total[1m]))',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossy',
    ],
    [
        'avg(rate(http_requests_total))',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossy',
    ],
    ['abs(sum(queue_depth))', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['sum(avg_over_time(queue_depth[5m]))', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    ['stddev(queue_depth)', { clauses: [clause({ metricName: 'queue_depth' })] }, 'lossy'],
    [
        'median(queue_depth)',
        { clauses: [clause({ metricName: 'queue_depth', aggregation: 'quantile', quantile: 0.95 })] },
        'lossy',
    ],
    [
        'quantile(0.99, request_latency_ms)',
        { clauses: [clause({ metricName: 'request_latency_ms', aggregation: 'quantile', quantile: 0.95 })] },
        'lossy',
    ],
    [
        'sum(rate(http_requests_total[5m:1m]))',
        { clauses: [clause({ metricName: 'http_requests_total', aggregation: 'rate' })] },
        'lossy',
    ],
    ['up == 1', { clauses: [clause({ metricName: 'up' })] }, 'lossy'],
    ['sum({__name__=~"queue_.*"})', null, 'lossy'],
    ['vector(1)', null, 'lossy'],
    ['sum(', null, 'lossy'],
    ['sum by (a (x)', null, 'lossy'],
    ['x{a=b}', null, 'lossy'],
    ['sum(x{a="unterminated})', null, 'lossy'],
]

const metricsQuery = (fields: Partial<MetricsQuery>): MetricsQuery => ({
    kind: NodeKind.MetricsQuery,
    clauses: [],
    dateRange: { date_from: '-6h' },
    interval: 'minute_5',
    ...fields,
})

describe('metrics query languages', () => {
    describe('PromQL parser and printer', () => {
        it.each([
            'sum by (service_name) (rate(http_requests_total{code=~"5.."}[5m]))',
            'histogram_quantile(0.99, sum by (le) (rate({"http.server.duration_bucket", "http.route"="/"}[5m])))',
            'a / on() group_left sum(b)',
            '-sum(x) ^ 2',
            '(a + b) * c',
            'a - (b - c)',
            '2 ^ 3 ^ 2',
            'sum(x) offset 1h',
            'x > bool 1',
            'quantile by (k) (0.9, x)',
            'label_replace(x, "clause", "a", "", "") or y',
            'x @ 1700000000',
            'rate(x[5m:30s])',
            'max_over_time(x[1h:5m] @ end())',
            'count_values("version", build_info)',
        ])('prints %s so that it parses back to the same tree', (text) => {
            const parsed = parsePromQL(text)
            expect(parsePromQL(printPromQL(parsed))).toEqual(parsed)
        })

        it.each(['sum(', 'x{a=b}', 'x{a="b}', 'sum by (a (x)', '}', 'x[5m', '', 'sum(x) @ end()'])(
            'rejects %j with a position',
            (text) => {
                expect(() => parsePromQL(text)).toThrow(PromQLParseError)
            }
        )

        it('reads quoted UTF-8 metric and label names', () => {
            expect(parsePromQL('{"http.server.duration", "http.route"="/x"}')).toEqual({
                type: 'selector',
                name: 'http.server.duration',
                matchers: [{ label: 'http.route', op: '=', value: '/x' }],
            })
        })
    })

    describe('regex anchoring', () => {
        it.each(['^(?:a|b)$', 'users', '^/api', 'health$', '^$', 'a|b', '^foo.*bar$', '(?:a|b)$', '^foo|bar$', '^a|b'])(
            'keeps %j through PromQL',
            (pattern) => {
                expect(promRegexToBuilderRegex(builderRegexToPromRegex(pattern))).toEqual(pattern)
            }
        )

        it.each([
            ['users', '.*users.*'],
            ['^(?:a|b)$', 'a|b'],
            ['a|b', '.*(?:a|b).*'],
            ['^/api', '/api.*'],
            ['^foo|bar$', '.*(?:^foo|bar$).*'],
        ])('anchors builder regex %j as PromQL %j', (builder, prom) => {
            expect(builderRegexToPromRegex(builder)).toEqual(prom)
        })

        it.each([
            ['a|b', '^(?:a|b)$'],
            ['.*a|b.*', '^(?:.*a|b.*)$'],
        ])('reads PromQL regex %j as builder regex %j', (prom, builder) => {
            expect(promRegexToBuilderRegex(prom)).toEqual(builder)
            expect(builderRegexToPromRegex(builder)).toEqual(prom)
        })
    })

    describe('PromQL → builder', () => {
        it.each(PROMQL_CASES)('%s', (text, expected, kind) => {
            const result = promqlToBuilder(text)
            if (expected === null) {
                expect(result.value).toBeNull()
                expect(result.issues.length).toBeGreaterThan(0)
                return
            }
            expect(result.value).not.toBeNull()
            expect(canonicalBuilder(result.value!)).toEqual(canonicalBuilder(expected))
            if (kind === 'lossless') {
                expect(result.issues).toEqual([])
            } else {
                expect(result.issues.length).toBeGreaterThan(0)
            }
        })

        it.each(
            PROMQL_CASES.filter(
                ([, expected, kind]) =>
                    expected &&
                    kind === 'lossless' &&
                    expected.clauses.every((clause) => clause.aggregation !== 'histogram_quantile')
            )
        )('switching %s to the builder and back is lossless', (text) => {
            const conversion = convertMetricsQuery(metricsQuery({ language: 'promql', promql: text }), 'builder')
            expect(conversion.issues).toEqual([])
            const back = convertMetricsQuery(conversion.query, 'promql')
            expect(back.issues).toEqual([])
            expect(canonicalPromQL(back.query.promql!)).toEqual(canonicalPromQL(text))
        })
    })

    describe('builder → PromQL', () => {
        it.each([
            ['gauge sum', 'sum(queue_depth)'],
            ['gauge avg', 'avg({"process.cpu.utilization"})'],
            ['counter rate', 'sum(rate({"http.server.request.count"}))'],
            ['p95', 'quantile(0.95, request_latency_ms)'],
            ['histogram p99', 'histogram_quantile(0.99, sum by (le) (rate({"http.server.duration_bucket"})))'],
            ['multi-value chip regex', 'sum(queue_depth{service_name=~"api|worker"})'],
            [
                'group by two dotted',
                'sum by ("http.route", "http.request.method") (rate({"http.server.request.count"}))',
            ],
            [
                'error ratio formula',
                'sum(rate({"http.server.request.count", "http.response.status_code"=~"5.*"})) / sum(rate({"http.server.request.count"})) * 100',
            ],
            [
                'two series without formula',
                'label_replace(sum(queue_depth), "clause", "a", "", "") or label_replace(avg({"process.cpu.utilization"}), "clause", "b", "", "")',
            ],
        ])('writes %s as %s', (name, expected) => {
            expect(builderToPromql(LOSSLESS_BUILDER_FIXTURES[name])).toEqual({ value: expected, issues: [] })
        })

        it('spreads an ungrouped series over a grouped one with on() group_left', () => {
            const result = builderToPromql({
                clauses: [
                    clause({ name: 'a', metricName: 'errors', aggregation: 'rate', groupBy: [{ key: 'job' }] }),
                    clause({ name: 'b', metricName: 'requests', aggregation: 'rate' }),
                ],
                formula: 'a / b',
            })
            expect(result).toEqual({
                value: 'sum by (job) (rate(errors)) / on() group_left sum(rate(requests))',
                issues: [],
            })
        })
    })

    describe('round trips', () => {
        it.each(Object.keys(LOSSLESS_BUILDER_FIXTURES))('%s: builder → PromQL → builder', (name) => {
            const builder = LOSSLESS_BUILDER_FIXTURES[name]
            const promql = builderToPromql(builder)
            expect(promql.issues).toEqual([])
            const back = promqlToBuilder(promql.value!)
            expect(back.issues).toEqual([])
            expect(canonicalBuilder(back.value!)).toEqual(canonicalBuilder(builder))
        })

        it.each(Object.keys(LOSSLESS_BUILDER_FIXTURES))('%s: builder → SQL → builder', (name) => {
            const builder = LOSSLESS_BUILDER_FIXTURES[name]
            const sql = builderToSql(builder)
            expect(sql.issues).toEqual([])
            const back = sqlToBuilder(sql.value!)
            expect(back.issues).toEqual([])
            expect(canonicalBuilder(back.value!)).toEqual(canonicalBuilder(builder))
        })

        it.each(Object.keys(LOSSLESS_BUILDER_FIXTURES))('%s: PromQL → SQL → PromQL', (name) => {
            const promql = builderToPromql(LOSSLESS_BUILDER_FIXTURES[name]).value!
            const toSql = convertMetricsQuery(metricsQuery({ language: 'promql', promql }), 'sql')
            expect(toSql.issues).toEqual([])
            const back = convertMetricsQuery(toSql.query, 'promql')
            expect(back.issues).toEqual([])
            expect(back.query.promql).toEqual(promql)
        })

        it('keeps the date range, interval and display', () => {
            const query = metricsQuery({
                clauses: LOSSLESS_BUILDER_FIXTURES['gauge sum'].clauses,
                display: { type: 'bar' },
            })
            const { query: converted } = convertMetricsQuery(query, 'sql')
            expect(converted).toMatchObject({
                dateRange: query.dateRange,
                interval: 'minute_5',
                display: { type: 'bar' },
            })
            expect(converted.clauses).toEqual([])
            expect(converted.language).toEqual('sql')
        })
    })

    describe('lossy switches', () => {
        it.each<[string, MetricsQuery, 'builder' | 'promql' | 'sql']>([
            [
                'a resource-scoped filter to PromQL',
                metricsQuery({
                    clauses: [
                        clause({
                            metricName: 'queue_depth',
                            filters: [{ key: 'host.name', op: 'eq', value: 'a', scope: 'resource' }],
                        }),
                    ],
                }),
                'promql',
            ],
            [
                'a series the formula does not use',
                metricsQuery({
                    clauses: [clause({ name: 'a', metricName: 'x' }), clause({ name: 'b', metricName: 'y' })],
                    formula: 'a * 2',
                }),
                'promql',
            ],
            [
                'an ungrouped series spread over a grouped one, to SQL',
                metricsQuery({
                    clauses: [
                        clause({ name: 'a', metricName: 'x', groupBy: [{ key: 'job' }] }),
                        clause({ name: 'b', metricName: 'y' }),
                    ],
                    formula: 'a / b',
                }),
                'sql',
            ],
            ['a fixed range window', metricsQuery({ language: 'promql', promql: 'sum(rate(x[10m]))' }), 'sql'],
            [
                'handwritten SQL that averages raw samples',
                metricsQuery({
                    language: 'sql',
                    sql: "SELECT toStartOfInterval(timestamp, {interval}) AS time, avg(value) AS value FROM posthog.metrics WHERE metric_name = 'cpu' AND timestamp >= {date_from} AND timestamp < {date_to} GROUP BY time",
                }),
                'promql',
            ],
            [
                'handwritten SQL that counts samples in fixed buckets',
                metricsQuery({
                    language: 'sql',
                    sql: "select toStartOfMinute(timestamp) as time, count() as value from posthog.metrics where metric_name = 'up' group by time limit 10",
                }),
                'builder',
            ],
            [
                'a histogram quantile, which the builder can chart but not edit',
                metricsQuery({
                    language: 'promql',
                    promql: 'histogram_quantile(0.5, sum by (le) (rate({"http.server.duration_bucket"})))',
                }),
                'builder',
            ],
            [
                'SQL from another table',
                metricsQuery({ language: 'sql', sql: 'SELECT timestamp AS time, 1 AS value FROM events' }),
                'builder',
            ],
            ['PromQL that cannot be read', metricsQuery({ language: 'promql', promql: 'sum(' }), 'sql'],
        ])('warns about %s', (_name, query, to) => {
            expect(convertMetricsQuery(query, to).issues.length).toBeGreaterThan(0)
        })

        it('reports an edit to generated SQL that the builder cannot hold', () => {
            const sql = builderToSql(LOSSLESS_BUILDER_FIXTURES['gauge sum']).value!.replace(
                'ORDER BY time',
                'ORDER BY time DESC'
            )
            expect(convertMetricsQuery(metricsQuery({ language: 'sql', sql }), 'builder').issues).toEqual([
                GENERIC_LOSS_ISSUE,
            ])
        })

        it('reads a handwritten SQL query with a group-by', () => {
            const result = sqlToBuilder(`
                SELECT toStartOfInterval(timestamp, {interval}) AS time, service_name, max(value) AS value
                FROM posthog.metrics
                WHERE metric_name = 'queue_depth' AND service_name IN ('api', 'worker')
                    AND timestamp >= {date_from} AND timestamp < {date_to}
                GROUP BY time, service_name
            `)
            expect(result.value).toEqual({
                clauses: [
                    clause({
                        metricName: 'queue_depth',
                        aggregation: 'max',
                        filters: [{ key: 'service_name', op: 'regex', value: '^(?:api|worker)$' }],
                        groupBy: [{ key: 'service_name' }],
                    }),
                ],
            })
            expect(result.issues).toHaveLength(1)
        })
    })

    // The backend runs every fixture's SQL in SQL mode and compares it with the builder result
    // (products/metrics/backend/tests/test_metrics_query_languages.py). Set UPDATE_METRICS_SQL_FIXTURES=1 to refresh it.
    it('keeps the SQL fixtures for the backend in sync', () => {
        const fixturePath = path.join(__dirname, '__fixtures__', 'builder_sql.json')
        const generated = Object.fromEntries(
            Object.entries(LOSSLESS_BUILDER_FIXTURES).map(([name, builder]) => [
                name,
                { builder, sql: builderToSql(builder).value },
            ])
        )
        if (process.env.UPDATE_METRICS_SQL_FIXTURES) {
            fs.mkdirSync(path.dirname(fixturePath), { recursive: true })
            fs.writeFileSync(fixturePath, JSON.stringify(generated, null, 4) + '\n')
        }
        expect(JSON.parse(fs.readFileSync(fixturePath, 'utf-8'))).toEqual(generated)
    })
})
