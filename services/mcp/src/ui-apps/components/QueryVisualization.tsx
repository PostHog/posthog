import type { ReactElement } from 'react'

import { FunnelVisualizer } from './FunnelVisualizer'
import { inferVisualizationType } from './infer-visualization'
import { LifecycleVisualizer } from './LifecycleVisualizer'
import { PathsVisualizer } from './PathsVisualizer'
import { RetentionVisualizer } from './RetentionVisualizer'
import { StickinessVisualizer } from './StickinessVisualizer'
import { TableVisualizer } from './TableVisualizer'
import { TrendsVisualizer } from './TrendsVisualizer'
import type {
    FunnelResult,
    FunnelsQuery,
    HogQLResult,
    LifecycleQuery,
    LifecycleResult,
    PathsQuery,
    PathsResult,
    RetentionQuery,
    RetentionResult,
    StickinessQuery,
    StickinessResult,
    TrendsQuery,
    TrendsResult,
} from './types'
import { toTableResult } from './utils'

/** Data payload from MCP tools */
export interface QueryDataPayload {
    query?:
        | TrendsQuery
        | StickinessQuery
        | FunnelsQuery
        | LifecycleQuery
        | RetentionQuery
        | PathsQuery
        | Record<string, unknown>
    results:
        | TrendsResult
        | StickinessResult
        | FunnelResult
        | LifecycleResult
        | RetentionResult
        | PathsResult
        | HogQLResult
    /** Saved insight from `insight-query`; its `query` keeps the wrapper node that `query` drops */
    insight?: { query?: unknown }
    /** Column names for table-shaped results such as `WebStatsTableQuery` */
    columns?: string[]
    _posthogUrl?: string
}

export interface QueryVisualizationProps {
    data: unknown
}

export function QueryVisualization({ data }: QueryVisualizationProps): ReactElement | null {
    const payload = data as QueryDataPayload
    switch (inferVisualizationType(data)) {
        case 'trends':
            return (
                <TrendsVisualizer
                    // The host updates `data` in place, so key on the query to re-seed state per result.
                    key={JSON.stringify(payload.query)}
                    query={payload.query as TrendsQuery}
                    results={payload.results as TrendsResult}
                />
            )

        case 'funnel':
            return <FunnelVisualizer query={payload.query as FunnelsQuery} results={payload.results as FunnelResult} />

        case 'stickiness':
            return (
                <StickinessVisualizer
                    // The host updates `data` in place, so key on the query to re-seed state per result.
                    key={JSON.stringify(payload.query)}
                    query={payload.query as StickinessQuery}
                    results={payload.results as StickinessResult}
                />
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
                    // The host updates `data` in place, so key on the query to re-seed state per result.
                    key={JSON.stringify(payload.query)}
                    query={payload.query as RetentionQuery}
                    results={payload.results as RetentionResult}
                />
            )

        case 'paths':
            return <PathsVisualizer results={payload.results as PathsResult} />

        case 'table':
            return <TableVisualizer results={toTableResult(payload.query, payload.results, payload.columns)} />

        default:
            return null
    }
}
