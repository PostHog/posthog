import type { ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { FunnelVisualizer } from './FunnelVisualizer'
import { inferVisualizationType } from './infer-visualization'
import { LifecycleVisualizer } from './LifecycleVisualizer'
import { PathsVisualizer } from './PathsVisualizer'
import { RetentionVisualizer } from './RetentionVisualizer'
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
    TrendsQuery,
    TrendsResult,
} from './types'

/** Data payload from MCP tools */
interface DataPayload {
    query?: TrendsQuery | FunnelsQuery | LifecycleQuery | RetentionQuery | PathsQuery | Record<string, unknown>
    results: TrendsResult | FunnelResult | LifecycleResult | RetentionResult | PathsResult | HogQLResult
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
                    <TrendsVisualizer
                        // Re-seed chart type/config from scratch when a new query arrives — the host
                        // updates `data` in place (ontoolresult) rather than remounting the app.
                        key={JSON.stringify(payload.query)}
                        query={payload.query as TrendsQuery}
                        results={payload.results as TrendsResult}
                        title={getTitle()}
                    />
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

            case 'paths':
                return <PathsVisualizer results={payload.results as PathsResult} />

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
            case 'paths':
                return 'Paths'
            case 'table':
                return 'Query results'
            default:
                return 'Results'
        }
    }

    return (
        <Card>
            <CardContent>
                {/* Trends renders its own title inline with the chart controls. */}
                {visualizationType !== 'trends' && (
                    <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {getTitle()}
                    </div>
                )}
                {renderVisualization()}
            </CardContent>
        </Card>
    )
}
