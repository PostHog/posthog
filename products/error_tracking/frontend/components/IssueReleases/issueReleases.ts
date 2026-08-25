import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'

import { DateRange } from '~/queries/schema/schema-general'

/** Bars per release strip. The strips share the panel width with the label and count columns. */
export const RELEASE_TIMELINE_RESOLUTION = 40
export const MAX_VISIBLE_RELEASES = 5
/** Stacked mode has no per-release rows, so it can hold far more releases before folding. */
export const MAX_STACKED_RELEASES = 1000
/** zinc-400 as hex: the chart canvas cannot resolve a CSS variable for a bar color. */
export const UNATTRIBUTED_RELEASE_COLOR = '#9f9fa9'

/** The query returns at most this many releases, so the payload stays bounded whatever the cap. */
export const RELEASES_QUERY_LIMIT = MAX_STACKED_RELEASES + 1

/** One row of the releases query: namespace, version, build, `[bucket start (unix seconds), occurrences]`
 *  per bucket, total occurrences, and the number of releases in the range before the query limit. */
export type IssueReleasesQueryRow = [
    string | null,
    string | null,
    string | null,
    [number, number][],
    number,
    number | undefined,
]
const MIN_BUCKET_SECONDS = 60

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
    /** Distinct releases in the range, before folding into `other`. */
    releaseCount: number
    /** Every app namespace in the range, before the namespace filter, so a picker can list them. */
    namespaces: string[]
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

const NUMERIC_VERSION = /^\d+(\.\d+)*/

/** Newest release first. Dotted version numbers order by version; anything else (a commit hash, a
 *  date) orders by when it first appeared, since bucket granularity ties too often to lead. */
function compareReleases(left: IssueRelease, right: IssueRelease): number {
    const byVersion = compareVersions(right.version, left.version) || compareVersions(right.build, left.build)
    const byFirstSeen = right.firstSeenIndex - left.firstSeenIndex
    const numeric = NUMERIC_VERSION.test(left.version ?? '') && NUMERIC_VERSION.test(right.version ?? '')
    return (numeric ? byVersion || byFirstSeen : byFirstSeen || byVersion) || right.total - left.total
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
    maxVisibleReleases: number = MAX_VISIBLE_RELEASES,
    selectedNamespace: string | null = null
): IssueReleaseTimeline {
    const bucketCount = bucketing.bucketStarts.length
    const alignedFrom = bucketing.bucketStarts[0] ?? 0
    const releasesByKey = new Map<string, IssueRelease>()
    const namespaces = new Set<string>()
    let unattributed: IssueRelease | null = null
    let total = 0

    for (const [namespace, version, build, series] of rows) {
        const inRange = series
            .map(([bucket, count]) => [Math.floor((bucket - alignedFrom) / bucketing.bucketSeconds), count])
            .filter(([index]) => index >= 0 && index < bucketCount)
        if (inRange.length === 0) {
            continue
        }
        if (namespace) {
            namespaces.add(namespace)
        }
        if (selectedNamespace !== null && namespace !== selectedNamespace) {
            continue
        }
        const isUnattributed = !namespace && !version
        const key = isUnattributed ? 'unattributed' : releaseKey(namespace, version, build)
        let release = isUnattributed ? unattributed : releasesByKey.get(key)
        if (!release) {
            release = emptyRelease(key, namespace, version, build, bucketCount)
            if (isUnattributed) {
                unattributed = release
            } else {
                releasesByKey.set(key, release)
            }
        }
        for (const [index, count] of inRange) {
            total += count
            addCount(release, index, count)
        }
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
        // The query caps its rows, so past the cap the window count is the only true total.
        releaseCount:
            selectedNamespace === null
                ? Math.max(sorted.length, (rows[0]?.[5] ?? 0) - (unattributed ? 1 : 0))
                : sorted.length,
        namespaces: [...namespaces].sort(),
        total,
        maxBucketValue,
    }
}

export type IssueReleaseStripKind = 'release' | 'other' | 'unattributed'

export interface IssueReleaseStrip {
    release: IssueRelease
    kind: IssueReleaseStripKind
    label: string
    /** `label` prefixed with the app namespace when the timeline mixes several apps. */
    fullLabel: string
    color: string
}

/** Every strip the panel draws, in display order, with palette colors assigned to real releases. */
export function listReleaseStrips(timeline: IssueReleaseTimeline, palette: string[]): IssueReleaseStrip[] {
    const multipleApps = timeline.groups.length > 1
    const strips: IssueReleaseStrip[] = timeline.groups
        .flatMap((group) => group.releases)
        .map((release, index) => {
            const label = formatReleaseVersion(release)
            return {
                release,
                kind: 'release',
                label,
                fullLabel: multipleApps && release.namespace ? `${release.namespace} · ${label}` : label,
                color: palette[index % palette.length],
            }
        })
    if (timeline.other) {
        const label = pluralize(timeline.otherReleaseCount, 'other release')
        strips.push({
            release: timeline.other,
            kind: 'other',
            label,
            fullLabel: label,
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    if (timeline.unattributed) {
        const label = 'No release data'
        strips.push({
            release: timeline.unattributed,
            kind: 'unattributed',
            label,
            fullLabel: label,
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    return strips
}
