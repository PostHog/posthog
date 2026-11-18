import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { DateRange, InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType, HogQLMathType, IntervalType } from '~/types'

export interface InsightQueryFilters {
    properties: AnyPropertyFilter[]
    filterTestAccounts: boolean
}

const MAX_HOURS_FOR_HOURLY_INTERVAL = 25

// Buckets the summary series may return. Hourly windows stay under a day and daily windows come from
// a date picker, so no reachable range approaches this.
const MAX_SUMMARY_BUCKETS = 10000

export function getInterval(dateFrom: string | null | undefined, dateTo: string | null | undefined): IntervalType {
    const from = dateStringToDayJs(dateFrom ?? null)
    const to = dateStringToDayJs(dateTo ?? null) ?? dayjs()
    if (from && to.diff(from, 'hour') < MAX_HOURS_FOR_HOURLY_INTERVAL) {
        return 'hour'
    }
    return 'day'
}

// Exceptions carry their release as $app_namespace / $app_version / $app_build, the same identity the
// issue page's releases panel groups by. Coalescing a missing property to '' keeps it inside the
// aggregates below: a null would propagate through the comparison and drop the row instead of
// grouping it as "no release data".
const RELEASE_NAMESPACE = "coalesce(toString(properties.$app_namespace), '')"
const RELEASE_VERSION = "coalesce(toString(properties.$app_version), '')"
const RELEASE_BUILD = "coalesce(toString(properties.$app_build), '')"
const RELEASE_KEY = `tuple(${RELEASE_NAMESPACE}, ${RELEASE_VERSION}, ${RELEASE_BUILD})`
const HAS_RELEASE = `${RELEASE_VERSION} != ''`

// toString() is load-bearing: a bare dateTrunc returns a typed DateTime that the query API serializes
// with the project's UTC offset attached, which the client reads back as an instant and converts,
// shifting every bucket away from the wall-clock keys it joins against. Rendering it server-side
// leaves a plain string with nothing left to reinterpret.
function bucketExpr(interval: IntervalType): string {
    return `toString(dateTrunc('${interval}', timestamp))`
}

/**
 * Headline totals for the selected period and the equal-length period before it.
 *
 * Runs over the doubled window and splits on `currentStart`, so both halves come back from one
 * scan. Distinct counts have to be measured over the whole period rather than summed from the series
 * query: a person, session, or release active on more than one day would otherwise be counted once
 * per day. Column order is the contract `parseComparisonTotals` reads.
 */
export function buildComparisonTotalsQuery(currentStart: string, timezone: string): string {
    const current = `timestamp >= toDateTime('${currentStart}', '${timezone}')`
    const previous = `timestamp < toDateTime('${currentStart}', '${timezone}')`
    const exception = "event = '$exception'"
    const session = 'notEmpty($session_id)'
    return `
        SELECT
            countIf(${exception} AND ${current}) AS exceptions,
            countIf(${exception} AND ${previous}) AS previous_exceptions,
            uniqIf(person_id, ${exception} AND ${current}) AS affected_users,
            uniqIf(person_id, ${exception} AND ${previous}) AS previous_affected_users,
            uniqIf($session_id, ${session} AND ${current}) AS sessions,
            uniqIf($session_id, ${session} AND ${previous}) AS previous_sessions,
            uniqIf($session_id, ${exception} AND ${session} AND ${current}) AS crash_sessions,
            uniqIf($session_id, ${exception} AND ${session} AND ${previous}) AS previous_crash_sessions,
            uniqIf(${RELEASE_KEY}, ${exception} AND ${HAS_RELEASE} AND ${current}) AS releases,
            uniqIf(${RELEASE_KEY}, ${exception} AND ${HAS_RELEASE} AND ${previous}) AS previous_releases
        FROM events
        WHERE {filters}
    `
}

/**
 * The same measures per bucket over the selected period, for the metric tiles' sparklines. Column
 * order is the contract `parseSummaryBuckets` reads.
 *
 * The LIMIT is load-bearing. A HogQL query with no limit of its own is paginated at 100 rows, and
 * these rows are ordered oldest first, so a window longer than 100 buckets would drop its most
 * recent ones and the zero-fill would draw them as zeros. The cap is set above any window the date
 * picker can produce rather than at a number a real range could reach.
 */
export function buildSummarySeriesQuery(interval: IntervalType): string {
    return `
        SELECT
            ${bucketExpr(interval)} AS bucket,
            countIf(event = '$exception') AS exceptions,
            uniqIf(person_id, event = '$exception') AS affected_users,
            uniqIf($session_id, notEmpty($session_id)) AS sessions,
            uniqIf($session_id, event = '$exception' AND notEmpty($session_id)) AS crash_sessions,
            uniqIf(${RELEASE_KEY}, event = '$exception' AND ${HAS_RELEASE}) AS releases
        FROM events
        WHERE {filters}
        GROUP BY bucket
        ORDER BY bucket
        LIMIT ${MAX_SUMMARY_BUCKETS}
    `
}

/**
 * Exception volume per release, folded server-side into one row per release.
 *
 * Grouping by release and collecting the buckets into an array keeps a busy account to one row per
 * release rather than one per release and bucket, which is what lets the row cap bound the response.
 * Column order is the contract `parseReleaseRows` reads.
 */
export function buildReleaseBreakdownQuery(interval: IntervalType, maxRows: number): string {
    return `
        SELECT
            namespace,
            version,
            build,
            groupArray(tuple(bucket, occurrences)) AS series
        FROM (
            SELECT
                ${bucketExpr(interval)} AS bucket,
                ${RELEASE_NAMESPACE} AS namespace,
                ${RELEASE_VERSION} AS version,
                ${RELEASE_BUILD} AS build,
                count() AS occurrences
            FROM events
            WHERE event = '$exception' AND {filters}
            GROUP BY bucket, namespace, version, build
        )
        GROUP BY namespace, version, build
        ORDER BY sum(occurrences) DESC
        LIMIT ${maxRows}
    `
}

export function buildExceptionVolumeQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Exceptions',
                },
            ],
            interval,
            dateRange,
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
        // The card around the chart already draws the border, so the viz must not draw its own.
        embedded: true,
    }
}

export function buildIssuesCreatedQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Issues created',
                    math: HogQLMathType.HogQL,
                    // Cymbal stores issue_first_seen from the same event timestamp when it creates the fingerprint,
                    // so equality selects the event that created the issue rather than its later occurrences.
                    math_hogql: 'uniqIf(issue_id, timestamp = issue_first_seen)',
                },
            ],
            interval,
            dateRange,
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
        // The card around the chart already draws the border, so the viz must not draw its own.
        embedded: true,
    }
}

export function buildAffectedUsersQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Affected users',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            interval,
            dateRange,
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
        // The card around the chart already draws the border, so the viz must not draw its own.
        embedded: true,
    }
}

export function buildCrashFreeSessionsQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: null,
                    custom_name: 'Total sessions',
                    math: BaseMathType.UniqueSessions,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Sessions with crash',
                    math: BaseMathType.UniqueSessions,
                },
            ],
            interval,
            dateRange,
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
        // The card around the chart already draws the border, so the viz must not draw its own.
        embedded: true,
    }
}

/**
 * Exception volume per app, grouped by namespace alone.
 *
 * This cannot be folded out of the release breakdown: that query caps its rows, so past the cap an
 * app whose releases are all low-volume would vanish from the fold and the surviving apps' totals
 * and shares would be short by the dropped rows, with nothing saying so. Grouping by namespace here
 * keeps the app figures exact, and the row count is the number of apps rather than of releases.
 * Column order is the contract `parseReleaseRows` reads, with the release columns left empty.
 */
export function buildAppBreakdownQuery(interval: IntervalType, maxRows: number): string {
    return `
        SELECT
            namespace,
            '' AS version,
            '' AS build,
            groupArray(tuple(bucket, occurrences)) AS series
        FROM (
            SELECT
                ${bucketExpr(interval)} AS bucket,
                ${RELEASE_NAMESPACE} AS namespace,
                count() AS occurrences
            FROM events
            WHERE event = '$exception' AND {filters}
            GROUP BY bucket, namespace
        )
        GROUP BY namespace
        ORDER BY sum(occurrences) DESC
        LIMIT ${maxRows}
    `
}

export function insightNewUrl(query: InsightVizNode<TrendsQuery>): string {
    const editorQuery: InsightVizNode<TrendsQuery> = {
        ...query,
        full: true,
        showHeader: undefined,
        showTable: undefined,
        showFilters: undefined,
        embedded: undefined,
    }
    return urls.insightNew({ query: editorQuery })
}
