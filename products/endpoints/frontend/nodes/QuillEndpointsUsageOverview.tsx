import { Badge, Card, Skeleton, Text } from '@posthog/quill'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { EndpointsUsageOverviewItem, EndpointsUsageOverviewItemKey } from '~/queries/schema/schema-general'

import {
    ENDPOINTS_USAGE_OVERVIEW_GOOD_DIRECTION,
    ENDPOINTS_USAGE_OVERVIEW_KEYS,
    ENDPOINTS_USAGE_OVERVIEW_LABELS,
    endpointsUsageChangeTone,
    formatEndpointsUsageOverviewValue,
} from './endpointsUsageOverviewFormat'

export interface QuillEndpointsUsageOverviewProps {
    results: EndpointsUsageOverviewItem[] | undefined
    loading: boolean
}

const CHANGE_TOOLTIP = 'Compared with the previous period of the same length'

export function QuillEndpointsUsageOverview({ results, loading }: QuillEndpointsUsageOverviewProps): JSX.Element {
    const itemByKey = new Map((results ?? []).map((item) => [item.key, item]))

    return (
        <div
            className="grid grid-cols-2 gap-2 @min-[40rem]/main-content:grid-cols-4"
            aria-busy={loading}
            data-attr="endpoints-usage-overview"
        >
            {ENDPOINTS_USAGE_OVERVIEW_KEYS.map((key) => (
                <Card key={key} size="sm" className="min-w-0">
                    {loading ? (
                        <OverviewTileSkeleton metricKey={key} />
                    ) : (
                        <OverviewTile metricKey={key} item={itemByKey.get(key)} />
                    )}
                </Card>
            ))}
        </div>
    )
}

function OverviewTile({
    metricKey,
    item,
}: {
    metricKey: EndpointsUsageOverviewItemKey
    item: EndpointsUsageOverviewItem | undefined
}): JSX.Element {
    const label = ENDPOINTS_USAGE_OVERVIEW_LABELS[metricKey]
    const format = (value: number): string => formatEndpointsUsageOverviewValue(metricKey, value)

    if (!item) {
        return (
            <div className="flex flex-col px-3">
                <MetricTitle>{label}</MetricTitle>
                <Text size="xs" variant="muted" render={<div />} className="mt-2">
                    No data
                </Text>
            </div>
        )
    }

    const changePct = item.changeFromPreviousPct ?? null
    const tone = changePct != null ? endpointsUsageChangeTone(metricKey, changePct) : null
    const previous =
        item.previous != null ? `Previous period: ${formatEndpointsUsageOverviewValue(metricKey, item.previous)}` : null

    return (
        <Metric
            className="px-3"
            value={item.value ?? 0}
            formatValue={format}
            // A neutral change (a volume, or no change) shows as a plain badge instead of a colored pill.
            change={tone && tone !== 'neutral' && changePct != null ? { value: changePct } : null}
            goodDirection={ENDPOINTS_USAGE_OVERVIEW_GOOD_DIRECTION[metricKey] ?? 'up'}
            changeTooltip={CHANGE_TOOLTIP}
            restingSubtitle={previous}
        >
            <MetricHeader>
                <MetricTitle>{label}</MetricTitle>
                {tone === 'neutral' && changePct != null ? (
                    <Badge title={CHANGE_TOOLTIP}>
                        {changePct > 0 ? '+' : ''}
                        {changePct.toFixed(1)}%
                    </Badge>
                ) : (
                    tone && <MetricDelta />
                )}
            </MetricHeader>
            <MetricValue className="mt-2" />
            {previous && <MetricSubtitle className="mt-1" />}
        </Metric>
    )
}

// Mirrors the line boxes of a loaded tile so the grid keeps its height when the data arrives.
function OverviewTileSkeleton({ metricKey }: { metricKey: EndpointsUsageOverviewItemKey }): JSX.Element {
    return (
        <div className="flex flex-col px-3">
            <MetricHeader>
                <MetricTitle>{ENDPOINTS_USAGE_OVERVIEW_LABELS[metricKey]}</MetricTitle>
                <Skeleton className="h-4 w-12 shrink-0 rounded-full" />
            </MetricHeader>
            <div className="mt-2 flex h-10 items-center">
                <Skeleton className="h-7 w-20" />
            </div>
            <Skeleton className="mt-1 h-4 w-28" />
        </div>
    )
}
