import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { Query } from '~/queries/Query/Query'
import { EndpointsUsageTrendsQuery } from '~/queries/schema/schema-general'

export interface QuillEndpointsUsageChartCardProps {
    title: string
    description?: string
    query: EndpointsUsageTrendsQuery
    /** Changes on each refresh, so the query runs again instead of reading its cached result. */
    refreshKey: number
}

export function QuillEndpointsUsageChartCard({
    title,
    description,
    query,
    refreshKey,
}: QuillEndpointsUsageChartCardProps): JSX.Element {
    return (
        <Card size="sm" className="min-w-0">
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    {title}
                </CardTitle>
                {description && <CardDescription>{description}</CardDescription>}
            </CardHeader>
            <CardContent>
                <Query key={`${query.metric}-${refreshKey}`} query={query} readOnly />
            </CardContent>
        </Card>
    )
}
