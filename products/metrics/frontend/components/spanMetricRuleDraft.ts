import type { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'

import type { _MetricFilterApi } from '../generated/api.schemas'
import { MetricsViewerClause, metricFiltersForGroup } from './metricsViewerLogic'

export const DERIVED_SPAN_REQUESTS = 'posthog.derived.spans.requests'
export const DERIVED_SPAN_ERRORS = 'posthog.derived.spans.errors'
export const DERIVED_SPAN_DURATION = 'posthog.derived.spans.duration'

type SavableSpanMetric = typeof DERIVED_SPAN_REQUESTS | typeof DERIVED_SPAN_ERRORS | typeof DERIVED_SPAN_DURATION

const SAVABLE_SPAN_METRICS: Record<SavableSpanMetric, { label: string; suffix: string }> = {
    [DERIVED_SPAN_REQUESTS]: { label: 'requests', suffix: 'requests' },
    [DERIVED_SPAN_ERRORS]: { label: 'errors', suffix: 'errors' },
    [DERIVED_SPAN_DURATION]: { label: 'request duration', suffix: 'duration' },
}

export const isSavableSpanMetric = (metricName: string): metricName is SavableSpanMetric =>
    metricName in SAVABLE_SPAN_METRICS

// The derived series name these enums, the span rule matches the OTel ints.
const SPAN_KIND_CODES: Record<string, string> = {
    unspecified: '0',
    internal: '1',
    server: '2',
    client: '3',
    producer: '4',
    consumer: '5',
}
const SPAN_STATUS_CODES: Record<string, string> = { unset: '0', ok: '1', error: '2' }
const SERVER_KIND = SPAN_KIND_CODES.server
const ERROR_STATUS = SPAN_STATUS_CODES.error

// A derived span series reads an unscoped key from the resource attributes first, then the span
// attributes. A rule reads one map, so it picks the resource map for OTel resource namespaces.
const RESOURCE_KEYS = new Set(['env'])
const RESOURCE_KEY_PREFIXES = [
    'cloud.',
    'container.',
    'deployment.',
    'device.',
    'faas.',
    'host.',
    'k8s.',
    'os.',
    'process.',
    'service.',
    'telemetry.',
]

// Mirrors MAX_METRIC_RULE_GROUP_BY_KEYS in products/logs/backend/models.py.
const MAX_RULE_GROUP_BY_KEYS = 5

const OP_TO_OPERATOR: Record<NonNullable<_MetricFilterApi['op']>, string> = {
    eq: 'exact',
    neq: 'is_not',
    regex: 'regex',
    not_regex: 'not_regex',
}

export interface RuleFilter {
    key: string
    operator: string
    value?: string
    type: 'span_attribute' | 'span_resource_attribute'
}

// Columns every span has, so a negative filter on them never meets a missing value.
const COLUMN_KEYS = new Set(['kind', 'status_code', 'service_name', 'name'])

/** A metric rule built from one derived span query, plus what the rule cannot carry over. */
export interface SpanMetricRuleDraft {
    rule: Pick<LogsMetricRuleApi, 'name' | 'metric_name' | 'source' | 'value_attribute' | 'filter_group' | 'group_by'>
    /** The filters the rule applies, all of which must match. */
    filters: RuleFilter[]
    /** True when a filter compares text, which the rule does without regard to case. */
    ignoresCase: boolean
    /** Filters the rule cannot express, shown as a warning. */
    droppedFilters: string[]
    /** Group-by keys the rule cannot express, shown as a warning. */
    droppedGroupByKeys: string[]
    /** True when the rule adds a server-span filter the query did not have. */
    addsServerFilter: boolean
}

const isResourceKey = (filter: Pick<_MetricFilterApi, 'key' | 'scope'>): boolean =>
    filter.scope === 'resource' ||
    (filter.scope !== 'attribute' &&
        (RESOURCE_KEYS.has(filter.key) || RESOURCE_KEY_PREFIXES.some((prefix) => filter.key.startsWith(prefix))))

const isKindKey = (key: string): boolean => key === 'span.kind' || key === 'kind'
const isStatusKey = (key: string): boolean => key === 'span.status_code' || key === 'status_code'

function toRuleFilter(filter: _MetricFilterApi): RuleFilter | null {
    const operator = OP_TO_OPERATOR[filter.op ?? 'eq']
    const enumCodes = isKindKey(filter.key) ? SPAN_KIND_CODES : isStatusKey(filter.key) ? SPAN_STATUS_CODES : null
    if (enumCodes) {
        // A pattern over the enum names has no equivalent over the ints the rule matches.
        const code = enumCodes[filter.value]
        if (!code || (operator !== 'exact' && operator !== 'is_not')) {
            return null
        }
        return { key: isKindKey(filter.key) ? 'kind' : 'status_code', operator, value: code, type: 'span_attribute' }
    }
    if (filter.key === 'service.name' || filter.key === 'service_name') {
        return { key: 'service_name', operator, value: filter.value, type: 'span_attribute' }
    }
    if (filter.key === 'span.name' || filter.key === 'name') {
        return { key: 'name', operator, value: filter.value, type: 'span_attribute' }
    }
    return {
        key: filter.key,
        operator,
        value: filter.value,
        type: isResourceKey(filter) ? 'span_resource_attribute' : 'span_attribute',
    }
}

function toRuleGroupByKey(key: string): string {
    if (key === 'service.name' || key === 'service_name') {
        return 'service_name'
    }
    if (key === 'span.name' || key === 'name') {
        return 'name'
    }
    if (isKindKey(key)) {
        return 'kind'
    }
    if (isStatusKey(key)) {
        return 'status_code'
    }
    return isResourceKey({ key }) ? `resource_attributes.${key}` : `attributes.${key}`
}

// The chart reads a missing attribute as an empty string, so `!=` and `!~` count spans without it.
// The rule never matches a missing value, so those filters also accept an unset attribute.
function toFilterGroupValue(filter: RuleFilter): RuleFilter | { type: 'OR'; values: RuleFilter[] } {
    const negative = filter.operator === 'is_not' || filter.operator === 'not_regex'
    if (!negative || COLUMN_KEYS.has(filter.key)) {
        return filter
    }
    return { type: 'OR', values: [filter, { key: filter.key, operator: 'is_not_set', type: filter.type }] }
}

const sanitizeMetricNamePart = (part: string): string =>
    part
        .toLowerCase()
        .replace(/[^a-z0-9._-]+/g, '_')
        .replace(/^[^a-z]+/, '')

/**
 * Builds a span metric rule that keeps counting what a derived span query shows. Errors and
 * duration, like the derived series, cover server spans, so every rule adds a server-span filter
 * unless the query already filters on span kind.
 */
export function buildSpanMetricRuleDraft(
    metricName: string,
    filters: _MetricFilterApi[],
    groupByKeys: string[]
): SpanMetricRuleDraft | null {
    if (!isSavableSpanMetric(metricName)) {
        return null
    }
    const { label, suffix } = SAVABLE_SPAN_METRICS[metricName]

    const ruleFilters: RuleFilter[] = []
    const droppedFilters: string[] = []
    for (const filter of filters) {
        const ruleFilter = toRuleFilter(filter)
        if (ruleFilter) {
            ruleFilters.push(ruleFilter)
        } else {
            droppedFilters.push(`${filter.key} ${filter.op ?? 'eq'} ${filter.value}`)
        }
    }
    const addsServerFilter = !filters.some((filter) => isKindKey(filter.key))
    if (addsServerFilter) {
        ruleFilters.push({ key: 'kind', operator: 'exact', value: SERVER_KIND, type: 'span_attribute' })
    }
    if (metricName === DERIVED_SPAN_ERRORS) {
        ruleFilters.push({ key: 'status_code', operator: 'exact', value: ERROR_STATUS, type: 'span_attribute' })
    }

    const groupBy = groupByKeys.map(toRuleGroupByKey)
    const keptGroupBy = groupBy.slice(0, MAX_RULE_GROUP_BY_KEYS)

    const service = filters.find(
        (filter) => (filter.key === 'service.name' || filter.key === 'service_name') && (filter.op ?? 'eq') === 'eq'
    )?.value
    const serviceName = service ? sanitizeMetricNamePart(service) : ''

    return {
        rule: {
            name: service ? `${service} ${label}` : `All services ${label}`,
            metric_name: ['spans', serviceName, suffix].filter(Boolean).join('.'),
            source: 'spans',
            value_attribute: metricName === DERIVED_SPAN_DURATION ? 'duration_ms' : null,
            // The API rejects an empty group, and no filter_group matches every span.
            filter_group: ruleFilters.length
                ? { type: 'AND', values: [{ type: 'AND', values: ruleFilters.map(toFilterGroupValue) }] }
                : null,
            group_by: keptGroupBy,
        },
        filters: ruleFilters,
        ignoresCase: ruleFilters.some((filter) => filter.key !== 'kind' && filter.key !== 'status_code'),
        droppedFilters,
        droppedGroupByKeys: groupByKeys.slice(MAX_RULE_GROUP_BY_KEYS),
        addsServerFilter,
    }
}

/** The rule draft for a query of one derived span series, or why the query can't be saved as one. */
export function spanMetricSaveState(
    clauses: MetricsViewerClause[],
    formula: string
): { draft: SpanMetricRuleDraft | null; disabledReason?: string } | null {
    if (!clauses.some((clause) => isSavableSpanMetric(clause.metricName))) {
        return null
    }
    if (clauses.length > 1 || formula) {
        return { draft: null, disabledReason: 'Save as metric works on a query with one series and no formula' }
    }
    const [clause] = clauses
    return {
        draft: buildSpanMetricRuleDraft(
            clause.metricName,
            metricFiltersForGroup(clause.filterGroup),
            clause.groupByKeys
        ),
    }
}
