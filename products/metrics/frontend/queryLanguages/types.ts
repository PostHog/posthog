import type { MetricsQuery, MetricsQueryClause } from '~/queries/schema/schema-general'

/** The builder form of a metrics query: the pivot every conversion goes through. */
export type BuilderQuery = Pick<MetricsQuery, 'clauses' | 'formula'>

export type BuilderClause = MetricsQueryClause

/** A clause in the builder's current form: the legacy `rate` and `increase` aggregations mean `sum` over that range function. */
export const normalizeClause = (clause: BuilderClause): BuilderClause =>
    clause.aggregation === 'rate' || clause.aggregation === 'increase'
        ? { ...clause, aggregation: 'sum', rangeFunction: clause.aggregation }
        : clause

/**
 * The result of a best-effort conversion. `value` is null when nothing usable came out.
 * Each issue names one part of the source that the target cannot express or that changes meaning.
 * No issues means the conversion is lossless.
 */
export interface ConversionResult<T> {
    value: T | null
    issues: string[]
}

/** Alias for the n-th clause a conversion creates, matching the builder's a, b, c… */
export const clauseAlias = (index: number): string => String.fromCharCode('a'.charCodeAt(0) + index)

/** The engine runs `quantile` only at 0.95, the builder's p95. */
export const ENGINE_QUANTILE = 0.95

// Mirrors MAX_CLAUSES in metricsViewerLogic and the backend's MAX_CLAUSES_PER_QUERY.
export const MAX_CONVERTED_CLAUSES = 10

/** Ingestion stores `service.name` in its own column, and both PromQL and SQL call it `service_name`. */
export const normalizeLabelKey = (key: string): string => (key === 'service.name' ? 'service_name' : key)

// The PromQL label that keeps the series of a multi-series query apart, as the builder's clause alias does.
export const CLAUSE_LABEL = 'clause'

// PromQL makes a division by zero ±Inf or NaN, which the chart shows as a gap.
export const PROMQL_DIVISION_ISSUE =
    'Where a formula divides by zero, PromQL shows a gap, but the builder and SQL show 0.'

// The backend fills an interval with no SQL row with 0. The builder computes the formula there, with every series at 0.
export const SQL_EMPTY_INTERVAL_ISSUE =
    "Where no series has data in an interval, SQL shows 0, but the builder shows the formula's value with every series at 0."

/** Issues about values the target computes differently. The query itself converts without change. */
export const VALUE_ONLY_ISSUES = new Set([PROMQL_DIVISION_ISSUE, SQL_EMPTY_INTERVAL_ISSUE])
