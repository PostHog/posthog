import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import {
    ErrorTrackingIssueRelease,
    ErrorTrackingReleaseSeries,
    ErrorTrackingReleasesQueryResponse,
} from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { PreviewPropertyFilter } from '../IssueFilterPreview/issueFilterPreviewLogic'

/** Bars per release strip. The strips share the panel width with the label and count columns. */
export const RELEASE_TIMELINE_RESOLUTION = 40
export const MAX_VISIBLE_RELEASES = 5
/** Stacked mode has no per-release rows, so it can hold far more releases before folding. */
export const MAX_STACKED_RELEASES = 1000
/** zinc-400 as hex: the chart canvas cannot resolve a CSS variable for a bar color. */
export const UNATTRIBUTED_RELEASE_COLOR = '#9f9fa9'

export function formatReleaseVersion(release: Pick<ErrorTrackingIssueRelease, 'version' | 'build'>): string {
    if (!release.version) {
        return 'Unknown version'
    }
    return release.build ? `${release.version} (${release.build})` : release.version
}

/** A release count for display. A truncated response counted only the releases the query returned, so it reads as a lower bound. */
export function formatReleaseCount(count: number, noun: string, truncated: boolean): string {
    const number = humanFriendlyNumber(count)
    return `${truncated ? `${number}+` : number} ${pluralize(count, noun, undefined, false)}`
}

export type IssueReleaseStripKind = 'release' | 'other' | 'unattributed'

export interface IssueReleaseStrip {
    key: string
    kind: IssueReleaseStripKind
    series: ErrorTrackingReleaseSeries
    /** Set for `release` strips only. */
    release: ErrorTrackingIssueRelease | null
    label: string
    /** `label` prefixed with the app namespace when the response mixes several apps. */
    fullLabel: string
    color: string
}

/** Every strip the panel draws, in display order, with palette colors assigned to real releases. */
export function listReleaseStrips(
    response: ErrorTrackingReleasesQueryResponse,
    palette: string[]
): IssueReleaseStrip[] {
    const multipleApps = new Set(response.results.map((release) => release.namespace)).size > 1
    const strips: IssueReleaseStrip[] = response.results.map((release, index) => {
        const label = formatReleaseVersion(release)
        return {
            key: [release.namespace ?? '', release.version ?? '', release.build ?? ''].join('\0'),
            kind: 'release',
            series: release,
            release,
            label,
            fullLabel: multipleApps && release.namespace ? `${release.namespace} · ${label}` : label,
            color: palette[index % palette.length],
        }
    })
    if (response.other) {
        const label = formatReleaseCount(
            response.other_release_count,
            'other release',
            response.release_count_truncated
        )
        strips.push({
            key: 'other',
            kind: 'other',
            series: response.other,
            release: null,
            label,
            fullLabel: label,
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    if (response.unattributed) {
        const label = 'No release data'
        strips.push({
            key: 'unattributed',
            kind: 'unattributed',
            series: response.unattributed,
            release: null,
            label,
            fullLabel: label,
            color: UNATTRIBUTED_RELEASE_COLOR,
        })
    }
    return strips
}

function propertyFilter(key: string, value: string | null): PreviewPropertyFilter {
    return value
        ? { key, value, operator: PropertyOperator.Exact }
        : { key, value: null, operator: PropertyOperator.IsNotSet }
}

/**
 * The filters a click on the strip applies, empty when the strip cannot be filtered. A missing property filters on
 * "is not set" so a click never leaves a stale chip from an earlier click. The app namespace stays with the panel's
 * app picker and never becomes a chip.
 */
export function releasePropertyFilters(strip: IssueReleaseStrip): PreviewPropertyFilter[] {
    if (strip.kind === 'other') {
        return []
    }
    return [
        propertyFilter('$app_version', strip.release?.version ?? null),
        propertyFilter('$app_build', strip.release?.build ?? null),
    ]
}

/** The app pinned by an `$app_namespace` chip with one exact value. The app picker mirrors this chip. */
export function selectedAppNamespace(filterGroup: UniversalFiltersGroup): string | null {
    const firstGroup = filterGroup.values[0]
    if (!isUniversalGroupFilterLike(firstGroup)) {
        return null
    }
    const filter = firstGroup.values.find(
        (candidate) =>
            !isUniversalGroupFilterLike(candidate) &&
            candidate.type === PropertyFilterType.Event &&
            candidate.key === '$app_namespace'
    )
    if (!filter || isUniversalGroupFilterLike(filter) || filter.type !== PropertyFilterType.Event) {
        return null
    }
    if ((filter.operator ?? PropertyOperator.Exact) !== PropertyOperator.Exact) {
        return null
    }
    const values = Array.isArray(filter.value) ? filter.value : [filter.value]
    const value = values.length === 1 ? values[0] : null
    return typeof value === 'string' && value ? value : null
}

export function maxBucketValue(strips: IssueReleaseStrip[]): number {
    return Math.max(0, ...strips.flatMap((strip) => strip.series.counts))
}
