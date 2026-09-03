import { normalizeBucket } from 'lib/utils/timeBuckets'

import {
    formatReleaseCount,
    formatReleaseVersion,
    UNATTRIBUTED_RELEASE_COLOR,
} from 'products/error_tracking/frontend/components/IssueReleases/issueReleases'

/** Values drawn as their own band. The rest fold into one "other" band. */
export const MAX_VISIBLE_BANDS = 6

/**
 * Releases the query folds over. Past this the lowest-volume releases are dropped, so a capped
 * response undercounts the "other" band while every named release stays exact. The response reports
 * whether it was capped, so the panel can show its count as a lower bound.
 */
export const MAX_RELEASE_ROWS = 500

export interface ReleaseIdentity {
    namespace: string | null
    version: string | null
    build: string | null
}

export interface ReleaseRow extends ReleaseIdentity {
    /** Occurrences per bucket, aligned with the bucket keys the row was parsed against. */
    counts: number[]
    total: number
}

/** One property filter a band click applies. A null value filters on "is not set". */
export interface BandFilter {
    key: string
    value: string | null
}

export interface ExceptionBand {
    key: string
    label: string
    color: string
    counts: number[]
    total: number
    /** Share of the period's exceptions, as a percentage. */
    share: number
    /** Filters a click applies, or null for a band that folds several values together. */
    filters: BandFilter[] | null
}

export interface ExceptionBreakdown {
    bands: ExceptionBand[]
    /** Named values the rows covered, before the visible/other split. */
    groupCount: number
    groupCountTruncated: boolean
    total: number
}

export const EMPTY_EXCEPTION_BREAKDOWN: ExceptionBreakdown = {
    bands: [],
    groupCount: 0,
    groupCountTruncated: false,
    total: 0,
}

function emptyToNull(value: unknown): string | null {
    const text = String(value ?? '')
    return text === '' ? null : text
}

/**
 * Project each release's `(bucket, occurrences)` pairs onto the full set of bucket keys.
 *
 * The query groups by release rather than emitting one row per bucket, so a release active over a
 * long window still costs one row. Buckets it reported nothing in stay 0 here, which keeps every
 * band the same length as the chart's x-axis. Every other figure is derived from the projected
 * counts, so the table and the chart cannot disagree about a release's volume.
 */
export function parseReleaseRows(rawRows: unknown[][], bucketKeys: string[]): ReleaseRow[] {
    const bucketIndex = new Map(bucketKeys.map((key, index) => [key, index]))
    return rawRows.map((row) => {
        const counts = bucketKeys.map(() => 0)
        for (const pair of (row[3] ?? []) as [unknown, unknown][]) {
            const index = bucketIndex.get(normalizeBucket(pair[0]))
            if (index !== undefined) {
                counts[index] += Number(pair[1] ?? 0)
            }
        }
        return {
            namespace: emptyToNull(row[0]),
            version: emptyToNull(row[1]),
            build: emptyToNull(row[2]),
            counts,
            total: counts.reduce((sum, count) => sum + count, 0),
        }
    })
}

/** One value of the property being broken down, with every release row that reported it. */
interface BandGroup {
    key: string
    label: string
    filters: BandFilter[]
    rows: ReleaseRow[]
}

interface MergedCounts {
    counts: number[]
    total: number
}

function mergeRows(rows: ReleaseRow[], bucketCount: number): MergedCounts {
    const counts = Array.from({ length: bucketCount }, () => 0)
    for (const row of rows) {
        row.counts.forEach((count, index) => {
            counts[index] += count
        })
    }
    return { counts, total: counts.reduce((sum, count) => sum + count, 0) }
}

/**
 * Rank the groups, give the busiest their own band, and fold the rest into one. A group that stands
 * for "the property was not set" keeps its filters, because filtering down to it is the point of
 * showing it; the folded band cannot be filtered, so it carries none.
 */
/** Prefix that no grouped value can produce, so a band named "other" cannot collide with the fold. */
const SYNTHETIC_KEY = '\0band:'

function foldBands(
    named: BandGroup[],
    unset: BandGroup | null,
    bucketKeys: string[],
    palette: string[],
    otherNoun: string,
    truncated: boolean
): ExceptionBreakdown {
    const bucketCount = bucketKeys.length
    const ranked = [...named]
        .map((group) => ({ group, merged: mergeRows(group.rows, bucketCount) }))
        .sort((a, b) => b.merged.total - a.merged.total)
    const visible = ranked.slice(0, MAX_VISIBLE_BANDS)
    const hidden = ranked.slice(MAX_VISIBLE_BANDS)
    const unsetMerged = unset ? mergeRows(unset.rows, bucketCount) : null
    const total = ranked.reduce((sum, { merged }) => sum + merged.total, 0) + (unsetMerged?.total ?? 0)
    const share = (value: number): number => (total > 0 ? (value / total) * 100 : 0)

    const bands: ExceptionBand[] = visible.map(({ group, merged }, index) => ({
        key: group.key,
        label: group.label,
        color: palette[index % palette.length],
        counts: merged.counts,
        total: merged.total,
        share: share(merged.total),
        filters: group.filters,
    }))

    if (hidden.length > 0) {
        const merged = mergeRows(
            hidden.flatMap(({ group }) => group.rows),
            bucketCount
        )
        bands.push({
            key: `${SYNTHETIC_KEY}other`,
            label: formatReleaseCount(hidden.length, `other ${otherNoun}`, truncated),
            color: UNATTRIBUTED_RELEASE_COLOR,
            counts: merged.counts,
            total: merged.total,
            share: share(merged.total),
            filters: null,
        })
    }

    if (unset && unsetMerged && unset.rows.length > 0) {
        bands.push({
            key: unset.key,
            label: unset.label,
            color: UNATTRIBUTED_RELEASE_COLOR,
            counts: unsetMerged.counts,
            total: unsetMerged.total,
            share: share(unsetMerged.total),
            filters: unset.filters,
        })
    }

    return { bands, groupCount: named.length, groupCountTruncated: truncated, total }
}

/**
 * Exceptions split by release.
 *
 * A release is identified by app namespace, version, and build together, matching the issue page's
 * releases panel, so the same version shipped by two apps stays two releases.
 */
export function buildReleaseBreakdown(rows: ReleaseRow[], bucketKeys: string[], palette: string[]): ExceptionBreakdown {
    const multipleApps = new Set(rows.filter((row) => row.version !== null).map((row) => row.namespace)).size > 1
    // A row carrying only a namespace has no release. The Releases tile counts releases the same way
    // (queries.ts, HAS_RELEASE), so the tile and this panel report the same number.
    const named: BandGroup[] = rows
        .filter((row) => row.version !== null)
        .map((row) => {
            const version = formatReleaseVersion(row)
            return {
                key: [row.namespace ?? '', row.version ?? '', row.build ?? ''].join('\0'),
                label: multipleApps && row.namespace ? `${row.namespace} · ${version}` : version,
                filters: [
                    { key: '$app_namespace', value: row.namespace },
                    { key: '$app_version', value: row.version },
                    { key: '$app_build', value: row.build },
                ],
                rows: [row],
            }
        })
    const unattributed = rows.filter((row) => row.version === null)
    return foldBands(
        named,
        {
            key: `${SYNTHETIC_KEY}unattributed`,
            label: 'No release data',
            filters: [
                { key: '$app_namespace', value: null },
                { key: '$app_version', value: null },
                { key: '$app_build', value: null },
            ],
            rows: unattributed,
        },
        bucketKeys,
        palette,
        'release',
        rows.length >= MAX_RELEASE_ROWS
    )
}

/**
 * Exceptions split by app, folded from the same release rows rather than a query of their own, so the
 * two panels can never disagree about the period's totals.
 */
export function buildAppBreakdown(rows: ReleaseRow[], bucketKeys: string[], palette: string[]): ExceptionBreakdown {
    const byNamespace = new Map<string, ReleaseRow[]>()
    for (const row of rows) {
        if (row.namespace === null) {
            continue
        }
        const existing = byNamespace.get(row.namespace)
        if (existing) {
            existing.push(row)
        } else {
            byNamespace.set(row.namespace, [row])
        }
    }
    const named: BandGroup[] = [...byNamespace.entries()].map(([namespace, namespaceRows]) => ({
        key: namespace,
        label: namespace,
        filters: [{ key: '$app_namespace', value: namespace }],
        rows: namespaceRows,
    }))
    return foldBands(
        named,
        {
            key: `${SYNTHETIC_KEY}unattributed`,
            label: 'No app data',
            filters: [{ key: '$app_namespace', value: null }],
            rows: rows.filter((row) => row.namespace === null),
        },
        bucketKeys,
        palette,
        'app',
        rows.length >= MAX_RELEASE_ROWS
    )
}
