import { Badge, Card, CardContent, Heading, Skeleton, Text } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

import { EndpointsUsageOverviewItem } from '~/queries/schema/schema-general'

import {
    LABEL_FROM_KEY,
    type MetricKey,
    PRIMARY_METRICS,
    SECONDARY_METRICS,
    changeVariant,
    formatItem,
} from './endpointsUsageOverview'

function OverviewTile({
    metricKey,
    item,
    loading,
    primary,
}: {
    metricKey: MetricKey
    item: EndpointsUsageOverviewItem | undefined
    loading: boolean
    primary: boolean
}): JSX.Element {
    const changePct = item?.changeFromPreviousPct
    return (
        <Card size="sm" className="min-w-0" data-attr={`endpoints-usage-overview-${metricKey}`}>
            <CardContent className="flex flex-col gap-1">
                <Text size="xs" variant="muted">
                    {LABEL_FROM_KEY[metricKey]}
                </Text>
                {loading ? (
                    <Skeleton className={primary ? 'h-8 w-24' : 'h-6 w-20'} />
                ) : item ? (
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <Heading
                            size={primary ? '2xl' : 'xl'}
                            render={<div />}
                            className={cn('m-0 truncate tabular-nums', primary && 'font-bold')}
                        >
                            {formatItem(item)}
                        </Heading>
                        {changePct != null && (
                            <Badge
                                variant={changeVariant(metricKey, changePct)}
                                title="Compared with the previous period"
                            >
                                {changePct > 0 ? '+' : ''}
                                {changePct.toFixed(1)}%
                            </Badge>
                        )}
                    </div>
                ) : (
                    <Text variant="muted">No data</Text>
                )}
            </CardContent>
        </Card>
    )
}

export function QuillEndpointsUsageOverview({
    results,
    loading,
}: {
    results: EndpointsUsageOverviewItem[] | undefined
    loading: boolean
}): JSX.Element {
    const byKey = new Map((results ?? []).map((item) => [item.key as MetricKey, item]))

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 @min-[36rem]/main-content:grid-cols-3">
                {PRIMARY_METRICS.map((key) => (
                    <OverviewTile key={key} metricKey={key} item={byKey.get(key)} loading={loading} primary />
                ))}
            </div>
            <div className="grid grid-cols-2 gap-4 @min-[48rem]/main-content:grid-cols-3 @min-[64rem]/main-content:grid-cols-5">
                {SECONDARY_METRICS.map((key) => (
                    <OverviewTile key={key} metricKey={key} item={byKey.get(key)} loading={loading} primary={false} />
                ))}
            </div>
        </div>
    )
}
