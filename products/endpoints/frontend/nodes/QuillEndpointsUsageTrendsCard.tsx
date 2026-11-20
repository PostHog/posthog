import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Text } from '@posthog/quill'

import { EndpointsUsageTrendsQuery, EndpointsUsageTrendsQueryResponse } from '~/queries/schema/schema-general'

import { EndpointsUsageTrendsPlot } from './EndpointsUsageTrendsNode'
import { type TrendsDataPoint } from './endpointsUsageTrendsTransforms'
import { useEndpointsUsageQuery } from './useEndpointsUsageQuery'

export function QuillEndpointsUsageTrendsCard({
    title,
    description,
    query,
}: {
    title: string
    description?: string
    query: EndpointsUsageTrendsQuery
}): JSX.Element {
    const { response, responseLoading, responseError, retry } =
        useEndpointsUsageQuery<EndpointsUsageTrendsQueryResponse>(query)
    const results = response?.results as TrendsDataPoint[] | undefined

    return (
        <Card size="sm" className="min-w-0" data-attr={`endpoints-usage-chart-${query.metric}`}>
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    {title}
                </CardTitle>
                {description && <CardDescription>{description}</CardDescription>}
            </CardHeader>
            <CardContent>
                <div className="flex h-60 flex-col">
                    {responseLoading ? (
                        <Skeleton className="h-full w-full" />
                    ) : responseError ? (
                        <div className="flex h-full flex-col items-center justify-center gap-2">
                            <Text variant="muted">Could not load this chart.</Text>
                            <Button variant="outline" onClick={retry}>
                                Try again
                            </Button>
                        </div>
                    ) : !results || results.length === 0 ? (
                        <div className="flex h-full items-center justify-center">
                            <Text variant="muted">No data available for this period</Text>
                        </div>
                    ) : (
                        <EndpointsUsageTrendsPlot results={results} metric={query.metric} interval={query.interval} />
                    )}
                </div>
            </CardContent>
        </Card>
    )
}
