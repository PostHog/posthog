import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { FunnelVisualizer } from './FunnelVisualizer'
import { LifecycleVisualizer } from './LifecycleVisualizer'
import { RetentionVisualizer } from './RetentionVisualizer'
import { TableVisualizer } from './TableVisualizer'
import { TrendsVisualizer } from './TrendsVisualizer'
import type {
    FunnelResult,
    FunnelsQuery,
    HogQLResult,
    LifecycleQuery,
    LifecycleResult,
    RetentionQuery,
    RetentionResult,
    TrendsQuery,
    TrendsResult,
} from './types'

type VisualizationType = 'trends' | 'funnel' | 'lifecycle' | 'retention' | 'table'

/**
 * Lifecycle results share the trends shape but each item carries a `status` field
 * (`new` / `returning` / `resurrecting` / `dormant`), and dormant counts come back
 * negated from the backend so they render below zero.
 */
function isLifecycleResult(results: unknown): results is LifecycleResult {
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
function isTrendsResult(results: unknown): results is TrendsResult {
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
function isFunnelResult(results: unknown): results is FunnelResult {
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
function isRetentionResult(results: unknown): results is RetentionResult {
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
 * Check if results look like HogQLResult (object with columns and results arrays).
 */
function isHogQLResult(results: unknown): results is HogQLResult {
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
function inferVisualizationType(data: unknown): VisualizationType | null {
    if (typeof data !== 'object' || data === null) {
        return null
    }

    const d = data as Record<string, unknown>
    const results = d.results

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
    if (isTrendsResult(results)) {
        return 'trends'
    }
    if (isFunnelResult(results)) {
        return 'funnel'
    }

    // Infer from query kind as fallback
    const query = d.query as Record<string, unknown> | undefined
    if (query?.kind === 'LifecycleQuery') {
        return 'lifecycle'
    }
    if (query?.kind === 'TrendsQuery') {
        return 'trends'
    }
    if (query?.kind === 'FunnelsQuery') {
        return 'funnel'
    }
    if (query?.kind === 'RetentionQuery') {
        return 'retention'
    }
    if (query?.kind === 'HogQLQuery') {
        return 'table'
    }

    return null
}

/** Data payload from MCP tools */
interface DataPayload {
    query?: TrendsQuery | FunnelsQuery | LifecycleQuery | RetentionQuery | Record<string, unknown>
    results: TrendsResult | FunnelResult | LifecycleResult | RetentionResult | HogQLResult
    _posthogUrl?: string
}

export interface ComponentProps {
    data: unknown
}

export function Component({ data }: ComponentProps): ReactElement {
    const payload = data as DataPayload
    const visualizationType = inferVisualizationType(data)

    if (!visualizationType) {
        return (
            <Card>
                <CardContent>
                    <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Results
                    </div>
                    <Empty>
                        <EmptyHeader>
                            <EmptyMedia>{emptyStateIllustration('generic')}</EmptyMedia>
                            <EmptyDescription>
                                This visualization type isn't supported in this view yet.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                </CardContent>
            </Card>
        )
    }

    const renderVisualization = (): ReactElement => {
        switch (visualizationType) {
            case 'trends':
                return (
                    <TrendsVisualizer query={payload.query as TrendsQuery} results={payload.results as TrendsResult} />
                )

            case 'funnel':
                return (
                    <FunnelVisualizer query={payload.query as FunnelsQuery} results={payload.results as FunnelResult} />
                )

            case 'lifecycle':
                return (
                    <LifecycleVisualizer
                        query={payload.query as LifecycleQuery}
                        results={payload.results as LifecycleResult}
                    />
                )

            case 'retention':
                return (
                    <RetentionVisualizer
                        query={payload.query as RetentionQuery}
                        results={payload.results as RetentionResult}
                    />
                )

            case 'table':
                return <TableVisualizer results={payload.results as HogQLResult} />

            default:
                return <div className="text-muted-foreground">Unknown visualization type: {visualizationType}</div>
        }
    }

    const getTitle = (): string => {
        switch (visualizationType) {
            case 'trends':
                return 'Trends'
            case 'funnel':
                return 'Funnel'
            case 'lifecycle':
                return 'Lifecycle'
            case 'retention':
                return 'Retention'
            case 'table':
                return 'Query results'
            default:
                return 'Results'
        }
    }

    return (
        <Card>
            <CardContent>
                <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {getTitle()}
                </div>
                {renderVisualization()}
            </CardContent>
        </Card>
    )
}
