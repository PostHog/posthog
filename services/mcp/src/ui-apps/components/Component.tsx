import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { ChartHeader } from './ChartHeader'
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

/** Data payload from MCP tools */
interface DataPayload {
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
                    <ChartHeader title="Results" />
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
                    <TrendsVisualizer
                        // The host updates `data` in place, so key on the query to re-seed state per result.
                        key={JSON.stringify(payload.query)}
                        query={payload.query as TrendsQuery}
                        results={payload.results as TrendsResult}
                    />
                )

            case 'funnel':
                return (
                    <FunnelVisualizer query={payload.query as FunnelsQuery} results={payload.results as FunnelResult} />
                )

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
                        query={payload.query as RetentionQuery}
                        results={payload.results as RetentionResult}
                    />
                )

            case 'paths':
                return <PathsVisualizer results={payload.results as PathsResult} />

            case 'table':
                return <TableVisualizer results={payload.results as HogQLResult} />

            default:
                return <div className="text-muted-foreground">Unknown visualization type: {visualizationType}</div>
        }
    }

    return (
        <Card>
            <CardContent>{renderVisualization()}</CardContent>
        </Card>
    )
}
