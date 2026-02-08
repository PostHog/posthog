import type { CSSProperties, ReactElement } from 'react'

import { FunnelVisualizer } from './FunnelVisualizer'
import { PostHogLink } from './PostHogLink'
import { TableVisualizer } from './TableVisualizer'
import { TrendsVisualizer } from './TrendsVisualizer'
import type { FunnelResult, FunnelsQuery, HogQLResult, TrendsQuery, TrendsResult } from './types'

type VisualizationType = 'trends' | 'funnel' | 'table'

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
    if (isTrendsResult(results)) {
        return 'trends'
    }
    if (isFunnelResult(results)) {
        return 'funnel'
    }

    // Infer from query kind as fallback
    const query = d.query as Record<string, unknown> | undefined
    if (query?.kind === 'TrendsQuery') {
        return 'trends'
    }
    if (query?.kind === 'FunnelsQuery') {
        return 'funnel'
    }
    if (query?.kind === 'HogQLQuery') {
        return 'table'
    }

    return null
}

/** Data payload from MCP tools */
interface DataPayload {
    query?: TrendsQuery | FunnelsQuery | Record<string, unknown>
    results: TrendsResult | FunnelResult | HogQLResult
    _posthogUrl?: string
}

export interface ComponentProps {
    data: unknown
    onOpenLink?: (url: string) => void
}

export function Component({ data, onOpenLink }: ComponentProps): ReactElement {
    const containerStyle: CSSProperties = {
        fontFamily:
            'var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif)',
        color: 'var(--color-text-primary, #101828)',
        backgroundColor: 'var(--color-background-primary, #fff)',
        padding: '1rem',
        borderRadius: 'var(--border-radius-lg, 0.5rem)',
        border: '1px solid var(--color-border-primary, #e5e7eb)',
    }

    const titleStyle: CSSProperties = {
        fontSize: '0.875rem',
        fontWeight: 600,
        color: 'var(--color-text-secondary, #6b7280)',
        marginBottom: '1rem',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
    }

    const payload = data as DataPayload
    const visualizationType = inferVisualizationType(data)

    if (!visualizationType) {
        return (
            <div style={containerStyle}>
                <div style={titleStyle}>Results</div>
                <div
                    style={{
                        padding: '1.5rem',
                        textAlign: 'center',
                        color: 'var(--color-text-secondary, #6b7280)',
                    }}
                >
                    <div style={{ marginBottom: '0.5rem' }}>
                        This visualization type isn't supported in this view yet.
                    </div>
                    {payload._posthogUrl && <PostHogLink url={payload._posthogUrl} onOpen={onOpenLink} />}
                </div>
            </div>
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

            case 'table':
                return <TableVisualizer results={payload.results as HogQLResult} />

            default:
                return (
                    <div style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                        Unknown visualization type: {visualizationType}
                    </div>
                )
        }
    }

    const getTitle = (): string => {
        switch (visualizationType) {
            case 'trends':
                return 'Trends'
            case 'funnel':
                return 'Funnel'
            case 'table':
                return 'Query results'
            default:
                return 'Results'
        }
    }

    return (
        <div style={containerStyle}>
            <div style={titleStyle}>{getTitle()}</div>
            {renderVisualization()}
            {payload._posthogUrl && <PostHogLink url={payload._posthogUrl} onOpen={onOpenLink} />}
        </div>
    )
}
