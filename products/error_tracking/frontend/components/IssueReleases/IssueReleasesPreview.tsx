import { useActions, useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import {
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { IssueReleaseRow } from './IssueReleaseRow'
import { IssueReleaseTimeline, ReleaseBucketing, listReleaseStrips } from './issueReleases'
import { issueReleasesLogic } from './issueReleasesLogic'
import { IssueReleasesStackedChart } from './IssueReleasesStackedChart'

export function IssueReleasesPreview({ issueId }: { issueId: string }): JSX.Element {
    const { timeline, releasesLoading, releasesError, selectedNamespace } = useValues(issueReleasesLogic({ issueId }))
    const { loadReleases, selectNamespace } = useActions(issueReleasesLogic({ issueId }))
    const { releasesViewMode } = useValues(issueFilterPreviewLogic)
    const { setReleasesViewMode } = useActions(issueFilterPreviewLogic)
    const hasReleases = timeline !== null && timeline.total > 0

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="releases" title="Releases">
                <div className="flex w-full items-center justify-between gap-3">
                    <ToggleGroup
                        size="sm"
                        aria-label="Releases view"
                        value={[releasesViewMode]}
                        onValueChange={(value) => {
                            const next = value[0]
                            if (next === 'list' || next === 'stacked') {
                                setReleasesViewMode(next)
                            }
                        }}
                    >
                        <ToggleGroupItem value="list" data-attr="error-tracking-issue-releases-view-list">
                            List
                        </ToggleGroupItem>
                        <ToggleGroupItem value="stacked" data-attr="error-tracking-issue-releases-view-stacked">
                            Stacked
                        </ToggleGroupItem>
                    </ToggleGroup>
                    <ReleasesSummary
                        timeline={timeline}
                        loading={releasesLoading}
                        selectedNamespace={selectedNamespace}
                        onSelectNamespace={selectNamespace}
                    />
                </div>
            </IssueFilterPreviewHeader>
            <div className="flex min-h-40 flex-col px-3 pb-3 pt-2">
                {releasesLoading ? (
                    <div className="flex min-h-40 flex-1 items-center justify-center">
                        <Spinner />
                    </div>
                ) : releasesError ? (
                    <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-2 text-center">
                        <Text variant="muted">Couldn't load releases for this issue.</Text>
                        <Button variant="default" size="sm" onClick={() => loadReleases()}>
                            Retry
                        </Button>
                    </div>
                ) : timeline === null || !hasReleases ? (
                    <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-1 text-center">
                        <Text variant="muted">No release information for these exceptions.</Text>
                        <Text size="xs" variant="muted">
                            Exceptions show up here once they carry the $app_namespace and $app_version properties.
                        </Text>
                    </div>
                ) : releasesViewMode === 'stacked' ? (
                    <IssueReleasesStackedChart timeline={timeline} />
                ) : (
                    <ReleaseTimeline timeline={timeline} />
                )}
            </div>
        </div>
    )
}

const ALL_APPS = '__all__'

function ReleasesSummary({
    timeline,
    loading,
    selectedNamespace,
    onSelectNamespace,
}: {
    timeline: IssueReleaseTimeline | null
    loading: boolean
    selectedNamespace: string | null
    onSelectNamespace: (namespace: string | null) => void
}): JSX.Element | null {
    if (loading) {
        return (
            <Skeleton className="h-4 w-24">
                <span>Loading…</span>
            </Skeleton>
        )
    }
    if (timeline === null || (timeline.releaseCount === 0 && timeline.namespaces.length === 0)) {
        return null
    }
    const releases = pluralize(timeline.releaseCount, 'release')
    if (timeline.namespaces.length <= 1) {
        const namespace = timeline.namespaces[0]
        return (
            <Text size="xs" variant="muted" className="truncate">
                {namespace ? `${namespace} · ${releases}` : releases}
            </Text>
        )
    }
    const appItems: Record<string, string> = {
        [ALL_APPS]: pluralize(timeline.namespaces.length, 'app'),
        ...Object.fromEntries(timeline.namespaces.map((namespace) => [namespace, namespace])),
    }
    return (
        <div className="flex min-w-0 items-center gap-2">
            <Select
                items={appItems}
                value={selectedNamespace ?? ALL_APPS}
                onValueChange={(value) => onSelectNamespace(value === ALL_APPS ? null : String(value))}
            >
                <SelectTrigger size="sm" aria-label="App" data-attr="error-tracking-issue-releases-app">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                    {Object.entries(appItems).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                            {label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Text size="xs" variant="muted" className="shrink-0">
                {releases}
            </Text>
        </div>
    )
}

function ReleaseTimeline({ timeline }: { timeline: IssueReleaseTimeline }): JSX.Element {
    const theme = useChartTheme()
    const strips = listReleaseStrips(timeline, theme.colors)

    return (
        <div className="flex flex-col gap-px">
            {strips.map((strip) => (
                <IssueReleaseRow
                    key={strip.release.key}
                    release={strip.release}
                    kind={strip.kind}
                    label={strip.label}
                    color={strip.color}
                    bucketing={timeline.bucketing}
                    maxValue={timeline.maxBucketValue}
                    total={timeline.total}
                />
            ))}
            <ReleaseTimelineAxis bucketing={timeline.bucketing} />
        </div>
    )
}

function ReleaseTimelineAxis({ bucketing }: { bucketing: ReleaseBucketing }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const { rangeStart: start, rangeEnd: end } = bucketing
    const spansDays = end - start >= 2 * 24 * 60 * 60
    const format = (unix: number): string =>
        dayjs(unix * 1000)
            .tz(timezone)
            .format(spansDays ? 'D MMM' : 'D MMM HH:mm')

    return (
        <div className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_4.5rem] gap-x-2 pt-1">
            <div className="col-start-2 flex justify-between border-t border-primary pt-1">
                <Text size="xxs" variant="muted">
                    {format(start)}
                </Text>
                <Text size="xxs" variant="muted">
                    {format(Math.round((start + end) / 2))}
                </Text>
                <Text size="xxs" variant="muted">
                    {format(end)}
                </Text>
            </div>
        </div>
    )
}
