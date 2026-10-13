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

import { ErrorTrackingReleasesQueryResponse } from '~/queries/schema/schema-general'

import { IssueFilterPreviewHeader } from '../IssueFilterPreview/IssueFilterPreviewHeader'
import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { IssueReleaseRow } from './IssueReleaseRow'
import { formatReleaseCount, IssueReleaseStrip, listReleaseStrips, maxBucketValue } from './issueReleases'
import { issueReleasesLogic } from './issueReleasesLogic'
import { IssueReleasesStackedChart } from './IssueReleasesStackedChart'

export function IssueReleasesPreview({ issueId }: { issueId: string }): JSX.Element {
    const { releases, releasesLoading, releasesError, selectedNamespace } = useValues(issueReleasesLogic({ issueId }))
    const { loadReleases, selectNamespace, selectStrip } = useActions(issueReleasesLogic({ issueId }))
    const { releasesViewMode } = useValues(issueFilterPreviewLogic)
    const { setReleasesViewMode } = useActions(issueFilterPreviewLogic)
    const hasReleases = releases !== null && (releases.results.length > 0 || releases.other !== null)

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
                        releases={releases}
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
                ) : releases === null || !hasReleases ? (
                    <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-1 text-center">
                        <Text variant="muted">No release information for these exceptions.</Text>
                        <Text size="xs" variant="muted">
                            Exceptions show up here once they carry the $app_version property. Add $app_namespace to
                            tell apps apart.
                        </Text>
                    </div>
                ) : releasesViewMode === 'stacked' ? (
                    <IssueReleasesStackedChart releases={releases} onSelectStrip={selectStrip} />
                ) : (
                    <ReleaseTimeline releases={releases} onSelectStrip={selectStrip} />
                )}
            </div>
        </div>
    )
}

const ALL_APPS = '__all__'

function ReleasesSummary({
    releases,
    loading,
    selectedNamespace,
    onSelectNamespace,
}: {
    releases: ErrorTrackingReleasesQueryResponse | null
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
    if (releases === null) {
        return null
    }
    const count = formatReleaseCount(releases.release_count, 'release', releases.release_count_truncated)
    // An active `$app_namespace` chip narrows the response to that app, so the picker stays to switch back.
    if (selectedNamespace === null) {
        if (releases.release_count === 0 && releases.namespaces.length === 0) {
            return null
        }
        if (releases.namespaces.length <= 1) {
            const namespace = releases.namespaces[0]
            return (
                <Text size="xs" variant="muted" className="truncate">
                    {namespace ? `${namespace} · ${count}` : count}
                </Text>
            )
        }
    }
    const namespaces = Array.from(new Set([...releases.namespaces, ...(selectedNamespace ? [selectedNamespace] : [])]))
    const appItems: Record<string, string> = {
        [ALL_APPS]: selectedNamespace ? 'All apps' : pluralize(namespaces.length, 'app'),
        ...Object.fromEntries(namespaces.map((namespace) => [namespace, namespace])),
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
                {count}
            </Text>
        </div>
    )
}

function ReleaseTimeline({
    releases,
    onSelectStrip,
}: {
    releases: ErrorTrackingReleasesQueryResponse
    onSelectStrip: (strip: IssueReleaseStrip) => void
}): JSX.Element {
    const theme = useChartTheme()
    const strips = listReleaseStrips(releases, theme.colors)
    const maxValue = maxBucketValue(strips)

    return (
        <div className="flex flex-col gap-px">
            {strips.map((strip) => (
                <IssueReleaseRow
                    key={strip.key}
                    strip={strip}
                    buckets={releases.buckets}
                    maxValue={maxValue}
                    total={releases.total}
                    onSelect={() => onSelectStrip(strip)}
                />
            ))}
            <ReleaseTimelineAxis dateFrom={releases.date_from} dateTo={releases.date_to} />
        </div>
    )
}

function ReleaseTimelineAxis({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const start = dayjs(dateFrom)
    const end = dayjs(dateTo)
    const spansDays = end.diff(start, 'day') >= 2
    const format = (date: dayjs.Dayjs): string => date.tz(timezone).format(spansDays ? 'D MMM' : 'D MMM HH:mm')

    return (
        <div className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_4.5rem] gap-x-2 pt-1">
            <div className="col-start-2 flex justify-between border-t border-primary pt-1">
                <Text size="xxs" variant="muted">
                    {format(start)}
                </Text>
                <Text size="xxs" variant="muted">
                    {format(dayjs((start.valueOf() + end.valueOf()) / 2))}
                </Text>
                <Text size="xxs" variant="muted">
                    {format(end)}
                </Text>
            </div>
        </div>
    )
}
