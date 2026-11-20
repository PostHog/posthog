import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton } from '@posthog/quill'

import { IntervalType } from '~/types'

import { EndpointsUsageTrendsChart } from './EndpointsUsageTrendsNode'
import { type EndpointsUsageMetric, type TrendsDataPoint } from './endpointsUsageTrendsTransforms'

export interface QuillEndpointsUsageTrendsProps {
    results: TrendsDataPoint[] | undefined
    loading: boolean
    error: string | null
    onRetry: () => void
    metric: EndpointsUsageMetric
    interval?: IntervalType
}

/** The chart body of a usage card: the card owns the border and the title. */
export function QuillEndpointsUsageTrends({
    results,
    loading,
    error,
    onRetry,
    metric,
    interval,
}: QuillEndpointsUsageTrendsProps): JSX.Element {
    if (loading) {
        return <Skeleton className="h-60 w-full" />
    }

    if (error) {
        return (
            <Empty className="h-60 py-0">
                <EmptyHeader>
                    <EmptyTitle>Couldn't load this chart</EmptyTitle>
                    <EmptyDescription>{error}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={onRetry} data-attr="endpoints-usage-chart-retry">
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    if (!results || results.length === 0) {
        return (
            <Empty className="h-60 py-0">
                <EmptyHeader>
                    <EmptyDescription>No executions in this period</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return <EndpointsUsageTrendsChart results={results} metric={metric} interval={interval} />
}
