import type { FunnelResult, HogQLResult, LifecycleResult, PathsResult, RetentionResult, TrendsResult } from './types'

export type VisualizationType = 'trends' | 'stickiness' | 'funnel' | 'lifecycle' | 'retention' | 'paths' | 'table'

/**
 * Lifecycle results share the trends shape but each item carries a `status` field
 * (`new` / `returning` / `resurrecting` / `dormant`), and dormant counts come back
 * negated from the backend so they render below zero.
 */
export function isLifecycleResult(results: unknown): results is LifecycleResult {
    if (!Array.isArray(results) || results.length === 0) {
        return false
    }
    const first = results[0] as Record<string, unknown>
    if (typeof first !== 'object' || first === null) {
        return false
    }
    const status = first.status
    return (
        typeof status === 'string' &&
        (status === 'new' || status === 'returning' || status === 'resurrecting' || status === 'dormant')
    )
}

/**
 * Check if results look like TrendsResult (array of items with data/labels arrays).
 */
export function isTrendsResult(results: unknown): results is TrendsResult {
    if (!Array.isArray(results) || results.length === 0) {
        return false
    }

    // TrendsResult items have: data (number[]), labels or days (string[])
    const first = results[0] as Record<string, unknown>
    return (
        typeof first === 'object' &&
        first !== null &&
        (Array.isArray(first.data) || Array.isArray(first.labels) || Array.isArray(first.days))
    )
}

/**
 * Check if results look like FunnelResult (array of steps with count/order/name).
 */
export function isFunnelResult(results: unknown): results is FunnelResult {
    if (!Array.isArray(results) || results.length === 0) {
        return false
    }

    // Handle both flat array and nested array formats
    const items = Array.isArray(results[0]) ? (results[0] as unknown[]) : results
    if (items.length === 0) {
        return false
    }

    // FunnelResult items have: name, count, order
    const first = items[0] as Record<string, unknown>
    return (
        typeof first === 'object' &&
        first !== null &&
        'count' in first &&
        ('order' in first || 'action_id' in first || 'name' in first)
    )
}

/**
 * Retention results are arrays of cohorts where each item has `values: [{ count, ... }]`
 * and a `date`/`label`. Distinct from trends (which uses `data`/`labels`/`days`).
 */
export function isRetentionResult(results: unknown): results is RetentionResult {
    if (!Array.isArray(results) || results.length === 0) {
        return false
    }
    const first = results[0] as Record<string, unknown>
    if (typeof first !== 'object' || first === null) {
        return false
    }
    if (!Array.isArray(first.values) || !('date' in first)) {
        return false
    }
    // A brand-new cohort can legitimately have an empty `values` array — accept it as long as
    // the surrounding shape is right. Only validate the inner `count` field when there's a row.
    if (first.values.length === 0) {
        return true
    }
    const firstValue = first.values[0] as Record<string, unknown>
    return typeof firstValue === 'object' && firstValue !== null && 'count' in firstValue
}

/**
 * Paths results are an array of edges, each with string `source`/`target` node keys
 * (`<stepIndex>_<value>`) and a numeric `value` (user count).
 */
export function isPathsResult(results: unknown): results is PathsResult {
    if (!Array.isArray(results) || results.length === 0) {
        return false
    }
    const first = results[0] as Record<string, unknown>
    return (
        typeof first === 'object' &&
        first !== null &&
        typeof first.source === 'string' &&
        typeof first.target === 'string' &&
        typeof first.value === 'number'
    )
}

/**
 * Check if results look like HogQLResult (object with columns and results arrays).
 */
export function isHogQLResult(results: unknown): results is HogQLResult {
    if (typeof results !== 'object' || results === null) {
        return false
    }

    const r = results as Record<string, unknown>
    return 'columns' in r && 'results' in r && Array.isArray(r.columns) && Array.isArray(r.results)
}

/**
 * Infer the visualization type from the data structure.
 * This mimics how the main PostHog app determines visualization from query/results.
 */
export function inferVisualizationType(data: unknown): VisualizationType | null {
    if (typeof data !== 'object' || data === null) {
        return null
    }

    const d = data as Record<string, unknown>
    const results = d.results

    // Resolve the query kind up front. Wrapper nodes (`DataVisualizationNode` for HogQL/SQL
    // insights, `InsightVizNode` for standard insights) carry the real query kind on
    // `source.kind` — unwrap so a formatted-results payload (where the structural guards below
    // can't match) still resolves to the right visualization.
    const query = d.query as Record<string, unknown> | undefined
    const kind = unwrapQueryKind(query)

    // Infer from results structure first (most reliable)
    if (isHogQLResult(results)) {
        return 'table'
    }
    // Retention must come before trends — its cohort rows could otherwise be misread.
    if (isRetentionResult(results)) {
        return 'retention'
    }
    // Lifecycle must come before trends — its rows pass `isTrendsResult` too.
    if (isLifecycleResult(results)) {
        return 'lifecycle'
    }
    // Paths must come before trends/funnel — its edge rows match neither, but keep it explicit.
    if (isPathsResult(results)) {
        return 'paths'
    }
    // Stickiness rows are structurally identical to trends (`data`/`labels`/`days`), so the query
    // kind is the only reliable signal — it must be checked before the `isTrendsResult` guard.
    // Stickiness renders a percentage-of-users distribution, not a raw-count time series.
    if (kind === 'StickinessQuery') {
        return 'stickiness'
    }
    if (isTrendsResult(results)) {
        return 'trends'
    }
    if (isFunnelResult(results)) {
        return 'funnel'
    }

    // Fall back to the query kind when the structural guards above can't match (e.g. a
    // formatted-results payload). Stickiness is handled above, ahead of the trends shape guard.
    if (kind === 'LifecycleQuery') {
        return 'lifecycle'
    }
    if (kind === 'TrendsQuery') {
        return 'trends'
    }
    if (kind === 'FunnelsQuery') {
        return 'funnel'
    }
    if (kind === 'RetentionQuery') {
        return 'retention'
    }
    if (kind === 'PathsQuery') {
        return 'paths'
    }
    if (kind === 'HogQLQuery') {
        return 'table'
    }

    return null
}

/**
 * Resolve the effective query kind, unwrapping the wrapper nodes that carry their real
 * query on `source.kind`: `DataVisualizationNode` (HogQL/SQL insights) and `InsightVizNode`
 * (standard insights). Returns the wrapper's own kind when there's nothing to unwrap.
 */
function unwrapQueryKind(query: Record<string, unknown> | undefined): string | undefined {
    if (!query) {
        return undefined
    }
    if (query.kind === 'DataVisualizationNode' || query.kind === 'InsightVizNode') {
        const source = query.source as Record<string, unknown> | undefined
        if (source && typeof source.kind === 'string') {
            return source.kind
        }
    }
    return typeof query.kind === 'string' ? query.kind : undefined
}
