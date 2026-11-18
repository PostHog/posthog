import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconEllipsis, IconStar, IconStarFilled, IconTrash } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Skeleton,
    Spinner,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { releaseLogic } from './releaseLogic'
import { releaseMetricsLogic } from './releaseMetricsLogic'
import { ReleaseMetricSparkline } from './ReleaseMetricSparkline'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseRow } from './releaseUtils'

const MAX_METRICS = 5

function MetricCard({
    row,
    insightId,
    primary,
}: {
    row: ReleaseRow
    insightId: number
    primary: boolean
}): JSX.Element {
    const { metrics } = useValues(releaseMetricsLogic)
    const { canEditReleases } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)
    const metric = metrics[insightId]
    const ids = row.metricInsightIds
    const setIds = (next: number[]): void => updateRelease(row.id, { metric_insight_ids: next })

    return (
        <div
            className="flex min-w-0 flex-col overflow-hidden rounded-md border border-border"
            data-attr="release-metric"
        >
            <div className="flex min-w-0 flex-col gap-1 px-3 pt-2.5">
                <div className="flex min-w-0 items-center justify-between gap-2">
                    {metric?.status === 'ready' ? (
                        <LinkPrimitive
                            to={urls.insightView(metric.shortId as InsightShortId)}
                            className="truncate text-xs font-medium text-foreground hover:underline"
                        >
                            {metric.name}
                        </LinkPrimitive>
                    ) : metric?.status === 'failed' ? (
                        <Text size="xs" variant="muted">
                            This metric could not load.
                        </Text>
                    ) : (
                        <Skeleton className="h-3 w-32" />
                    )}
                    <div className="flex shrink-0 items-center gap-1">
                        {primary && (
                            <Text size="xxs" variant="muted" className="flex items-center gap-1">
                                <IconStarFilled className="size-3" />
                                Primary
                            </Text>
                        )}
                        {canEditReleases && (
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={
                                        <Button
                                            size="icon-xs"
                                            variant="default"
                                            aria-label="Metric actions"
                                            data-attr="release-metric-menu"
                                        />
                                    }
                                >
                                    <IconEllipsis />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                    {!primary && (
                                        <DropdownMenuItem
                                            onClick={() => setIds([insightId, ...ids.filter((id) => id !== insightId)])}
                                            data-attr="release-metric-make-primary"
                                        >
                                            <IconStar />
                                            Make primary
                                        </DropdownMenuItem>
                                    )}
                                    <DropdownMenuItem
                                        variant="destructive"
                                        onClick={() => setIds(ids.filter((id) => id !== insightId))}
                                        data-attr="release-metric-remove"
                                    >
                                        <IconTrash />
                                        Remove metric
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                    </div>
                </div>
                <Text size="lg" weight="semibold" className="text-2xl tabular-nums">
                    {metric?.status === 'ready' ? (
                        metric.value === null ? (
                            '–'
                        ) : (
                            humanFriendlyNumber(metric.value)
                        )
                    ) : metric?.status === 'failed' ? (
                        '–'
                    ) : (
                        <Skeleton className="h-6 w-16" />
                    )}
                </Text>
            </div>
            <div className="h-14">
                {metric?.status === 'ready' && metric.values.length > 1 && (
                    <ReleaseMetricSparkline values={metric.values} labels={metric.labels} />
                )}
            </div>
        </div>
    )
}

function AddMetricCombobox({ row }: { row: ReleaseRow }): JSX.Element {
    const { relatedSearch, relatedSearchLoading } = useValues(releaseRelatedLogic)
    const { searchRelated } = useActions(releaseRelatedLogic)
    const { updateRelease } = useActions(releaseLogic)
    const options = relatedSearch.insights.filter((insight) => !row.metricInsightIds.includes(insight.id))
    const names = new Map(options.map((insight) => [String(insight.id), insight.name]))

    return (
        <Combobox
            items={options.map((insight) => String(insight.id))}
            filter={null}
            value={null}
            onOpenChange={(open: boolean) => open && searchRelated('')}
            onInputValueChange={(value: string) => searchRelated(value)}
            onValueChange={(key: string | null) => {
                if (key) {
                    updateRelease(row.id, { metric_insight_ids: [...row.metricInsightIds, Number(key)] })
                }
            }}
            itemToStringLabel={(key: string) => names.get(key) ?? ''}
        >
            <ComboboxInput
                placeholder="Add a metric from a saved insight"
                aria-label="Add a metric from a saved insight"
                data-attr="release-add-metric"
            />
            <ComboboxContent>
                <ComboboxEmpty>
                    {relatedSearchLoading ? <Spinner /> : 'No saved insight matches that name.'}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key} data-attr="release-add-metric-option">
                            <span className="truncate">{names.get(key)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

export function ReleaseMetricsCard({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { loadMetrics } = useActions(releaseMetricsLogic)
    const ids = row.metricInsightIds

    useEffect(() => {
        if (ids.length) {
            loadMetrics(ids)
        }
    }, [ids.join(','), loadMetrics])

    if (!ids.length && !canEditReleases) {
        return null
    }

    return (
        <Card size="sm" data-attr="release-metrics">
            <CardHeader>
                <CardTitle>Metrics</CardTitle>
                <CardDescription>
                    {ids.length
                        ? 'How this release is doing. The primary metric shows in the releases table.'
                        : 'Pick the saved insights that tell you whether this release works.'}
                </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {ids.length > 0 && (
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
                        {ids.map((insightId, index) => (
                            <MetricCard key={insightId} row={row} insightId={insightId} primary={index === 0} />
                        ))}
                    </div>
                )}
                {canEditReleases &&
                    (ids.length < MAX_METRICS ? (
                        <AddMetricCombobox row={row} />
                    ) : (
                        <Text size="xs" variant="muted">
                            A release can have up to 5 metrics.
                        </Text>
                    ))}
            </CardContent>
        </Card>
    )
}
