import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { DateRange } from '~/queries/schema/schema-general'

/** Bars per release strip. The strips share the panel width with the label and count columns. */
export const RELEASE_TIMELINE_RESOLUTION = 40
export const MAX_VISIBLE_RELEASES = 8
/** Stacked mode has no per-release rows, so it can hold far more releases before folding. */
export const MAX_STACKED_RELEASES = 1000
/** zinc-400 as hex: the chart canvas cannot resolve a CSS variable for a bar color. */
export const UNATTRIBUTED_RELEASE_COLOR = '#9f9fa9'
const MIN_BUCKET_SECONDS = 60

/** One row of the releases query: bucket start (unix seconds), namespace, version, build, occurrences. */
export type IssueReleasesQueryRow = [number, string | null, string | null, string | null, number]

export interface ReleaseBucketing {
    bucketSeconds: number
    /** Unix seconds. Aligned to multiples of `bucketSeconds`, like `toStartOfInterval` in the query. */
    bucketStarts: number[]
    /** Unix seconds of the requested date range. The first bucket can start before `rangeStart`. */
    rangeStart: number
    rangeEnd: number
}

export interface IssueRelease {
    key: string
    namespace: string | null
    version: string | null
    build: string | null
    /** Occurrences per bucket, aligned with `ReleaseBucketing.bucketStarts`. */
    counts: number[]
    total: number
    firstSeenIndex: number
    lastSeenIndex: number
}

export interface IssueReleaseGroup {
    namespace: string | null
    releases: IssueRelease[]
}

export interface IssueReleaseTimeline {
    bucketing: ReleaseBucketing
    /** Visible releases, newest first, grouped by app namespace. */
    groups: IssueReleaseGroup[]
    /** Releases past `MAX_VISIBLE_RELEASES`, folded into one strip. */
    other: IssueRelease | null
    otherReleaseCount: number
    /** Exceptions that carry no app namespace or version. */
    unattributed: IssueRelease | null
    total: number
    maxBucketValue: number
}

export function computeReleaseBucketing(
    dateRange: DateRange,
    resolution: number = RELEASE_TIMELINE_RESOLUTION
): ReleaseBucketing | null {
    if (!dateRange.date_from) {
        return null
    }
    const from = dateStringToDayJs(dateRange.date_from)
    const to = dateStringToDayJs(dateRange.date_to ?? new Date().toISOString())
    if (!from || !to || !to.isAfter(from)) {
        return null
    }
    const totalSeconds = to.diff(from, 'second')
    const bucketSeconds = Math.max(MIN_BUCKET_SECONDS, Math.ceil(totalSeconds / resolution))
    const alignedFrom = Math.floor(from.unix() / bucketSeconds) * bucketSeconds
    const bucketStarts: number[] = []
    for (let start = alignedFrom; start < to.unix(); start += bucketSeconds) {
        bucketStarts.push(start)
    }
    return { bucketSeconds, bucketStarts, rangeStart: from.unix(), rangeEnd: to.unix() }
}

export function releaseKey(namespace: string | null, version: string | null, build: string | null): string {
    return [namespace ?? '', version ?? '', build ?? ''].join('\0')
}

export function formatReleaseVersion(release: Pick<IssueRelease, 'version' | 'build'>): string {
    if (!release.version) {
        return 'Unknown version'
    }
    return release.build ? `${release.version} (${release.build})` : release.version
}

function emptyRelease(
    key: string,
    namespace: string | null,
    version: string | null,
    build: string | null,
    bucketCount: number
): IssueRelease {
    return {
        key,
        namespace,
        version,
        build,
        counts: new Array(bucketCount).fill(0),
        total: 0,
        firstSeenIndex: -1,
        lastSeenIndex: -1,
    }
}

function addCount(release: IssueRelease, index: number, count: number): void {
    release.counts[index] += count
    release.total += count
    if (release.firstSeenIndex === -1 || index < release.firstSeenIndex) {
        release.firstSeenIndex = index
    }
    if (index > release.lastSeenIndex) {
        release.lastSeenIndex = index
    }
}

function compareVersions(left: string | null, right: string | null): number {
    return (left ?? '').localeCompare(right ?? '', undefined, { numeric: true, sensitivity: 'base' })
}

/** Newest release first: the one that appeared most recently, then the highest version. */
function compareReleases(left: IssueRelease, right: IssueRelease): number {
    return (
        right.firstSeenIndex - left.firstSeenIndex ||
        compareVersions(right.version, left.version) ||
        compareVersions(right.build, left.build) ||
        right.total - left.total
    )
}

function groupByNamespace(releases: IssueRelease[]): IssueReleaseGroup[] {
    const groups: IssueReleaseGroup[] = []
    for (const release of releases) {
        const group = groups.find(({ namespace }) => namespace === release.namespace)
        if (group) {
            group.releases.push(release)
        } else {
            groups.push({ namespace: release.namespace, releases: [release] })
        }
    }
    return groups
}

export function buildIssueReleaseTimeline(
    rows: IssueReleasesQueryRow[],
    bucketing: ReleaseBucketing,
    maxVisibleReleases: number = MAX_VISIBLE_RELEASES
): IssueReleaseTimeline {
    const bucketCount = bucketing.bucketStarts.length
    const alignedFrom = bucketing.bucketStarts[0] ?? 0
    const releasesByKey = new Map<string, IssueRelease>()
    let unattributed: IssueRelease | null = null
    let total = 0

    for (const [bucket, namespace, version, build, count] of rows) {
        const index = Math.floor((bucket - alignedFrom) / bucketing.bucketSeconds)
        if (index < 0 || index >= bucketCount) {
            continue
        }
        total += count
        if (!namespace && !version) {
            unattributed ??= emptyRelease('unattributed', null, null, null, bucketCount)
            addCount(unattributed, index, count)
            continue
        }
        const key = releaseKey(namespace, version, build)
        let release = releasesByKey.get(key)
        if (!release) {
            release = emptyRelease(key, namespace, version, build, bucketCount)
            releasesByKey.set(key, release)
        }
        addCount(release, index, count)
    }

    const sorted = [...releasesByKey.values()].sort(compareReleases)
    const visible = sorted.slice(0, maxVisibleReleases)
    const hidden = sorted.slice(maxVisibleReleases)
    let other: IssueRelease | null = null
    if (hidden.length > 0) {
        other = emptyRelease('other', null, null, null, bucketCount)
        for (const release of hidden) {
            release.counts.forEach((count, index) => {
                if (count > 0) {
                    addCount(other!, index, count)
                }
            })
        }
    }

    const strips = [...visible, other, unattributed].filter((release): release is IssueRelease => release !== null)
    const maxBucketValue = Math.max(0, ...strips.flatMap((release) => release.counts))

    return {
        bucketing,
        groups: groupByNamespace(visible),
        other,
        otherReleaseCount: hidden.length,
        unattributed,
        total,
        maxBucketValue,
    }
}

export type IssueReleaseStripKind = 'release' | 'other' | 'unattributed'

export interface IssueReleaseStrip {
    release: IssueRelease
    kind: IssueReleaseStripKind
    label: string
    color: string
}

/** Every strip the panel draws, in display order, with palette colors assigned to real releases. */
export function listReleaseStrips(timeline: IssueReleaseTimeline, palette: string[]): IssueReleaseStrip[] {
    const strips: IssueReleaseStrip[] = timeline.groups
        .flatMap((group) => group.releases)
        .map((release, index) => ({
            release,
            kind: 'release',
            label: formatReleaseVersion(release),
            color: palette[index % palette.length],
        }))
    if (timeline.other) {
        strips.push({
            release: timeline.other,
            kind: 'other',
            label: `${timeline.otherReleaseCount} other releases`,
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    if (timeline.unattributed) {
        strips.push({
            release: timeline.unattributed,
            kind: 'unattributed',
            label: 'No release data',
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    return strips
}
