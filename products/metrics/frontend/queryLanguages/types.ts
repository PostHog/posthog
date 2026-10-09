import type { MetricsQuery, MetricsQueryClause } from '~/queries/schema/schema-general'

/** The builder form of a metrics query: the pivot every conversion goes through. */
export type BuilderQuery = Pick<MetricsQuery, 'clauses' | 'formula'>

export type BuilderClause = MetricsQueryClause

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
