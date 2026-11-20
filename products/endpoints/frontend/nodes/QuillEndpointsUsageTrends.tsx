import { Empty, EmptyDescription, EmptyHeader, Skeleton } from '@posthog/quill'

import { IntervalType } from '~/types'

import { EndpointsUsageTrendsChart } from './EndpointsUsageTrendsNode'
import { type EndpointsUsageMetric, type TrendsDataPoint } from './endpointsUsageTrendsTransforms'

export interface QuillEndpointsUsageTrendsProps {
    results: TrendsDataPoint[] | undefined
    loading: boolean
    metric: EndpointsUsageMetric
    interval?: IntervalType
}

/** The chart body of a usage card: the card owns the border and the title. */
export function QuillEndpointsUsageTrends({
    results,
    loading,
    metric,
    interval,
}: QuillEndpointsUsageTrendsProps): JSX.Element {
    if (loading) {
        return <Skeleton className="h-60 w-full" />
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
