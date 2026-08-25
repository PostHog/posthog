import { useActions, useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { Button, Separator, Skeleton, Spinner, Text, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { IssueReleaseRow } from './IssueReleaseRow'
import { IssueReleaseGroup, IssueReleaseTimeline, ReleaseBucketing, listReleaseStrips } from './issueReleases'
import { issueReleasesLogic } from './issueReleasesLogic'
import { IssueReleasesStackedChart } from './IssueReleasesStackedChart'

export function IssueReleasesPreview({ issueId }: { issueId: string }): JSX.Element {
    const { timeline, releasesLoading, releasesError } = useValues(issueReleasesLogic({ issueId }))
    const { loadReleases } = useActions(issueReleasesLogic({ issueId }))
    const { releasesViewMode } = useValues(issueFilterPreviewLogic)
    const { setReleasesViewMode } = useActions(issueFilterPreviewLogic)
    const hasReleases = timeline !== null && timeline.total > 0

    return (
        <div className="flex flex-col">
            <IssueFilterPreviewHeader preview="releases" title="Releases">
                <div className="flex items-center gap-3">
                    <ReleasesSummary timeline={timeline} loading={releasesLoading} />
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

function ReleasesSummary({
    timeline,
    loading,
}: {
    timeline: IssueReleaseTimeline | null
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return (
            <Skeleton className="h-4 w-24">
                <span>Loading…</span>
            </Skeleton>
        )
    }
    if (timeline === null) {
        return null
    }
    const releaseCount = timeline.groups.reduce((sum, group) => sum + group.releases.length, 0)
    if (releaseCount === 0) {
        return null
    }
    const namespaces = timeline.groups.map((group) => group.namespace).filter((namespace) => namespace !== null)
    const label =
        namespaces.length === 1
            ? `${namespaces[0]} · ${pluralize(releaseCount + timeline.otherReleaseCount, 'release')}`
            : `${pluralize(releaseCount + timeline.otherReleaseCount, 'release')} across ${pluralize(namespaces.length, 'app')}`
    return (
        <Text size="xs" variant="muted" className="truncate">
            {label}
        </Text>
    )
}

function ReleaseTimeline({ timeline }: { timeline: IssueReleaseTimeline }): JSX.Element {
    const theme = useChartTheme()
    const strips = listReleaseStrips(timeline, theme.colors)
    const stripsByKey = new Map(strips.map((strip) => [strip.release.key, strip]))
    const showGroupTitles = timeline.groups.length > 1

    const renderRow = (key: string): JSX.Element | null => {
        const strip = stripsByKey.get(key)
        if (!strip) {
            return null
        }
        return (
            <IssueReleaseRow
                key={key}
                release={strip.release}
                kind={strip.kind}
                label={strip.label}
                color={strip.color}
                bucketing={timeline.bucketing}
                maxValue={timeline.maxBucketValue}
                total={timeline.total}
            />
        )
    }

    return (
        <div className="flex flex-col gap-px">
            {timeline.groups.map((group) => (
                <section key={group.namespace ?? ''} className="contents">
                    {showGroupTitles && <ReleaseGroupTitle group={group} />}
                    {group.releases.map((release) => renderRow(release.key))}
                </section>
            ))}
            {timeline.other && renderRow(timeline.other.key)}
            {timeline.unattributed && renderRow(timeline.unattributed.key)}
            <ReleaseTimelineAxis bucketing={timeline.bucketing} />
        </div>
    )
}

function ReleaseGroupTitle({ group }: { group: IssueReleaseGroup }): JSX.Element {
    return (
        <div className="flex h-8 items-center gap-3 px-1">
            <Text size="xxs" variant="muted" weight="semibold" render={<h3 />} className="!mb-0 shrink-0">
                {group.namespace ?? 'No app namespace'}
            </Text>
            <Separator className="min-w-0 flex-1" />
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
