import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
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
    Spinner,
    Text,
} from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { releaseMetricsLogic } from './releaseMetricsLogic'
import { ReleaseMetricTile } from './ReleaseMetricTile'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseRow } from './releaseUtils'

const MAX_METRICS = 5

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
                        ? 'How this release is doing against its goals. The primary metric shows in the releases table.'
                        : 'Pick the saved insights that tell you whether this release works, then set a goal for each.'}
                </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {ids.length > 0 && (
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-x-8 gap-y-4">
                        {ids.map((insightId, index) => (
                            <ReleaseMetricTile key={insightId} row={row} insightId={insightId} primary={index === 0} />
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
