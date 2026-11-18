import { type ReactElement, useEffect } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'

import { captureInsightViewed } from '../analytics/posthog'
import { ChartHeader } from './ChartHeader'
import { inferVisualizationType } from './infer-visualization'
import { QueryVisualization, type QueryDataPayload } from './QueryVisualization'
import { insightQueryProperties } from './utils'

export interface ComponentProps {
    data: unknown
}

export function Component({ data }: ComponentProps): ReactElement {
    const payload = data as QueryDataPayload
    const visualizationType = inferVisualizationType(data)
    const { queryKind, querySourceKind, display, funnelVizType } = insightQueryProperties(
        payload?.insight?.query ?? payload?.query
    )

    useEffect(() => {
        captureInsightViewed({
            queryKind,
            querySourceKind,
            display,
            funnelVizType,
            isSupported: visualizationType !== null,
        })
    }, [data, visualizationType, queryKind, querySourceKind, display, funnelVizType])

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

    return (
        <Card>
            <CardContent>
                <QueryVisualization data={data} />
            </CardContent>
        </Card>
    )
}
