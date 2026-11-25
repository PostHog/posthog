import { useActions } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { type ReleaseMetric, releaseMetricsLogic } from './releaseMetricsLogic'

export function ReleaseMetricTileName({
    insightId,
    metric,
}: {
    insightId: number
    metric: ReleaseMetric | undefined
}): JSX.Element {
    const { loadMetrics } = useActions(releaseMetricsLogic)

    if (metric?.status === 'ready') {
        return (
            <LinkPrimitive
                to={urls.insightView(metric.shortId as InsightShortId)}
                className="truncate text-[13px] text-muted-foreground hover:text-foreground hover:underline"
            >
                {metric.name}
            </LinkPrimitive>
        )
    }
    if (metric?.status === 'failed') {
        return (
            <Text size="xs" variant="muted" className="flex items-center gap-1">
                This metric could not load.
                <Button
                    size="xs"
                    variant="link-muted"
                    onClick={() => loadMetrics([insightId])}
                    data-attr="release-metric-retry"
                >
                    Try again
                </Button>
            </Text>
        )
    }
    return <Skeleton className="h-3 w-32" />
}
