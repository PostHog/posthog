import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, IntervalType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

export interface InsightQueryFilters {
    filterGroup: UniversalFiltersGroup
    filterTestAccounts: boolean
}

const MAX_HOURS_FOR_HOURLY_INTERVAL = 25

export function getInterval(dateFrom: string | null, dateTo: string | null): IntervalType {
    const from = dateStringToDayJs(dateFrom)
    const to = dateStringToDayJs(dateTo) ?? dayjs()
    if (from && to.diff(from, 'hour') < MAX_HOURS_FOR_HOURLY_INTERVAL) {
        return 'hour'
    }
    return 'day'
}

export function buildExceptionVolumeQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
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
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildAffectedUsersRateQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: null,
                    custom_name: 'Total users',
                    math: BaseMathType.UniqueUsers,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Affected users',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            interval,
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: 'B / A * 100', custom_name: 'Affected users %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildCrashFreeSessionsQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
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
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
        },
        showHeader: false,
        showTable: false,
    }
}

export const SUMMARY_STATS_QUERY = `
    SELECT
        countIf(event = '$exception') as total_exceptions,
        uniqIf(person_id, event = '$exception') as affected_users,
        uniqIf($session_id, notEmpty($session_id)) as total_sessions,
        uniqIf($session_id, event = '$exception' AND notEmpty($session_id)) as crash_sessions
    FROM events
    WHERE {filters}
`

export type SessionEndingStrategy = 'strict' | 'time' | 'event'

export interface SessionEndingStrategyOption {
    value: SessionEndingStrategy
    label: string
    description: string
}

export const SESSION_ENDING_STRATEGY_OPTIONS: SessionEndingStrategyOption[] = [
    {
        value: 'strict',
        label: 'Strict',
        description: 'Exception must be the very last event in the session',
    },
    {
        value: 'time',
        label: 'Time window',
        description: 'There might have been other events up to X seconds after last exception',
    },
    {
        value: 'event',
        label: 'Event window',
        description: 'At most X other events occurred after the exception',
    },
]

export const SESSION_ENDING_TIME_THRESHOLDS = [1, 5, 10, 30, 60]
export const SESSION_ENDING_EVENT_THRESHOLDS = [1, 2, 3, 4, 5]

export function buildSessionEndingIssuesQuery(strategy: SessionEndingStrategy, threshold: number): string {
    let condition: string
    const needsTimestamps = strategy === 'event'

    if (strategy === 'strict') {
        condition = `last_event = '$exception'`
    } else if (strategy === 'time') {
        condition = `notEmpty(last_exception_issue_id) AND dateDiff('second', last_exception_ts, last_event_ts) <= ${threshold}`
    } else {
        condition = `notEmpty(last_exception_issue_id) AND length(arrayFilter(t -> t > last_exception_ts, all_timestamps)) <= ${threshold}`
    }

    return `
    WITH session_data AS (
        SELECT
            $session_id as sid,
            argMax(event, timestamp) as last_event,
            argMaxIf(issue_id, timestamp, event = '$exception') as last_exception_issue_id,
            maxIf(timestamp, event = '$exception') as last_exception_ts,
            max(timestamp) as last_event_ts
            ${needsTimestamps ? ', groupArray(timestamp) as all_timestamps' : ''}
        FROM events
        WHERE {filters}
            AND notEmpty($session_id)
        GROUP BY $session_id
    ),
    exception_ended AS (
        SELECT
            ${strategy === 'strict' ? "argMaxIf(issue_id, timestamp, event = '$exception')" : 'last_exception_issue_id'} as issue_id,
            count() as sessions,
            groupArray(sid) as session_ids
        FROM session_data
        WHERE ${condition}
        GROUP BY issue_id
        ORDER BY sessions DESC
        LIMIT 10
    ),
    recorded_sessions AS (
        SELECT session_id
        FROM session_replay_events
        WHERE session_id IN (SELECT arrayJoin(session_ids) FROM exception_ended)
    )
    SELECT
        ee.issue_id,
        eti.name,
        eti.description,
        ee.sessions,
        arrayFirst(s -> has(rs.recorded_sessions_arr, s), ee.session_ids) as example_recording_session_id
    FROM exception_ended ee
    LEFT JOIN (
        SELECT id, name, description FROM system.error_tracking_issues
        WHERE id IN (SELECT issue_id FROM exception_ended)
    ) AS eti ON eti.id = ee.issue_id
    CROSS JOIN (
        SELECT groupArray(session_id) as recorded_sessions_arr FROM recorded_sessions
    ) AS rs
    ORDER BY sessions DESC
`
}

export type ErrorsByPageStrategy = 'visits' | 'events'

export interface ErrorsByPageStrategyOption {
    value: ErrorsByPageStrategy
    label: string
    description: string
}

export const ERRORS_BY_PAGE_STRATEGY_OPTIONS: ErrorsByPageStrategyOption[] = [
    {
        value: 'visits',
        label: 'By visits',
        description: 'Exceptions divided by pageviews for each URL',
    },
    {
        value: 'events',
        label: 'By events',
        description: 'Exceptions as a percentage of all events on each page',
    },
]

export function buildErrorsByPageQuery(strategy: ErrorsByPageStrategy): string {
    if (strategy === 'visits') {
        return `
    SELECT
        properties.$current_url as url,
        countIf(event = '$pageview') as denominator,
        countIf(event = '$exception') as errors,
        if(denominator > 0, round(errors / denominator * 100, 1), 0) as error_rate
    FROM events
    WHERE {filters}
        AND event IN ('$pageview', '$exception')
        AND notEmpty(properties.$current_url)
    GROUP BY url
    HAVING errors > 0 AND denominator > 0
    ORDER BY error_rate DESC
    LIMIT 10
`
    }

    return `
    SELECT
        properties.$current_url as url,
        count() as denominator,
        countIf(event = '$exception') as errors,
        if(denominator > 0, round(errors / denominator * 100, 1), 0) as error_rate
    FROM events
    WHERE {filters}
        AND notEmpty(properties.$current_url)
    GROUP BY url
    HAVING errors > 0 AND denominator > 0
    ORDER BY error_rate DESC
    LIMIT 10
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
