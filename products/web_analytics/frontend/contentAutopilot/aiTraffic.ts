import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'

import {
    DataTableNode,
    HogQLQuery,
    InsightVizNode,
    NodeKind,
    WebAnalyticsConversionGoal,
    WebOverviewItem,
    WebOverviewQuery,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import {
    AI_ASSISTANT_BREAKDOWN,
    AI_CHANNEL_FILTER,
    AI_VIEW,
    buildAiReferralTableQuery,
    buildAiReferralTrendQuery,
} from 'products/web_analytics/frontend/searchAndAi/searchAndAiQueries'

export const AI_TRAFFIC_DEFAULT_DATE_FROM = '-30d'
export const AI_TRAFFIC_TOP_CITED_PAGES = 500
export const AI_TRAFFIC_TOP_LANDED_PAGES = 1000

export type AiTrafficTrendMetric = 'visitors' | 'sessions'
export type AiTrafficPageStatus = 'cited_and_visited' | 'cited_not_visited' | 'visited_not_cited'
export type AiTrafficPageFilter = 'all' | AiTrafficPageStatus

export interface AiTrafficDateRange {
    dateFrom: string | null
    dateTo: string | null
}

export interface AiTrafficFilters extends AiTrafficDateRange {
    filterTestAccounts: boolean
}

export interface CitedPage {
    path: string
    answers: number
}

export interface LandedPage {
    path: string
    sessions: number
}

export interface AiTrafficPageRow {
    path: string
    answers: number
    sessions: number
    status: AiTrafficPageStatus
}

export interface AiTrafficSummary {
    aiVisitors: number
    aiSessions: number
    allSessions: number
}

export interface AiTrafficConversion {
    aiRate: number | null
    allRate: number | null
    aiConversions: number
}

/** Path of a cited URL or an entry pathname, without query string, fragment or trailing slash, so both sides of
 *  the comparison meet on the same key. The host is dropped because entry pathnames carry none. */
export const normalizePagePath = (urlOrPath: string): string => {
    let path = urlOrPath.trim()
    const schemeEnd = path.indexOf('://')
    if (schemeEnd !== -1) {
        const pathStart = path.indexOf('/', schemeEnd + 3)
        path = pathStart === -1 ? '/' : path.slice(pathStart)
    }
    path = path.split(/[?#]/)[0]
    if (!path.startsWith('/')) {
        path = `/${path}`
    }
    return path.length > 1 ? path.replace(/\/+$/, '') || '/' : path
}

const sumByPath = <T extends { path: string }>(rows: T[], count: (row: T) => number): Map<string, number> => {
    const totals = new Map<string, number>()
    for (const row of rows) {
        const path = normalizePagePath(row.path)
        totals.set(path, (totals.get(path) ?? 0) + count(row))
    }
    return totals
}

/** Pages the engines cite next to the pages AI-referred visitors land on, keyed by normalized path. Pages on both
 *  sides come first, then cited pages without visits, then visited pages that no check cited. */
export const joinCitedAndLanded = (cited: CitedPage[], landed: LandedPage[]): AiTrafficPageRow[] => {
    const answersByPath = sumByPath(cited, (page) => page.answers)
    const sessionsByPath = sumByPath(landed, (page) => page.sessions)
    const paths = new Set([...answersByPath.keys(), ...sessionsByPath.keys()])
    const statusOrder: Record<AiTrafficPageStatus, number> = {
        cited_and_visited: 0,
        cited_not_visited: 1,
        visited_not_cited: 2,
    }
    return [...paths]
        .map((path): AiTrafficPageRow => {
            const answers = answersByPath.get(path) ?? 0
            const sessions = sessionsByPath.get(path) ?? 0
            const status: AiTrafficPageStatus =
                answers > 0 && sessions > 0
                    ? 'cited_and_visited'
                    : answers > 0
                      ? 'cited_not_visited'
                      : 'visited_not_cited'
            return { path, answers, sessions, status }
        })
        .sort(
            (a, b) =>
                statusOrder[a.status] - statusOrder[b.status] ||
                b.answers - a.answers ||
                b.sessions - a.sessions ||
                a.path.localeCompare(b.path)
        )
}

export const countPagesByStatus = (rows: AiTrafficPageRow[]): Record<AiTrafficPageStatus, number> => {
    const counts: Record<AiTrafficPageStatus, number> = {
        cited_and_visited: 0,
        cited_not_visited: 0,
        visited_not_cited: 0,
    }
    for (const row of rows) {
        counts[row.status] += 1
    }
    return counts
}

export const aiTrafficTrendQuery = (filters: AiTrafficFilters, metric: AiTrafficTrendMetric): InsightVizNode =>
    buildAiReferralTrendQuery(
        {
            dateFilter: {
                dateFrom: filters.dateFrom,
                dateTo: filters.dateTo,
                interval: getDefaultInterval(filters.dateFrom, filters.dateTo),
                isIntervalManuallySet: false,
            },
            filterTestAccounts: filters.filterTestAccounts,
            properties: [],
        },
        AI_ASSISTANT_BREAKDOWN,
        metric === 'visitors' ? BaseMathType.UniqueUsers : BaseMathType.UniqueSessions
    )

export const aiTrafficEntryPagesQuery = (
    filters: AiTrafficFilters,
    conversionGoal: WebAnalyticsConversionGoal | null
): DataTableNode =>
    buildAiReferralTableQuery(
        {
            dateFilter: {
                dateFrom: filters.dateFrom,
                dateTo: filters.dateTo,
                interval: getDefaultInterval(filters.dateFrom, filters.dateTo),
                isIntervalManuallySet: false,
            },
            filterTestAccounts: filters.filterTestAccounts,
            properties: [],
            compareFilter: { compare: false },
            conversionGoal,
        },
        WebStatsBreakdown.InitialPage
    )

export const aiTrafficOverviewQuery = (
    filters: AiTrafficFilters,
    { aiOnly, conversionGoal }: { aiOnly: boolean; conversionGoal: WebAnalyticsConversionGoal | null }
): WebOverviewQuery => ({
    kind: NodeKind.WebOverviewQuery,
    dateRange: { date_from: filters.dateFrom, date_to: filters.dateTo },
    properties: aiOnly ? [AI_CHANNEL_FILTER] : [],
    compareFilter: { compare: false },
    conversionGoal,
    filterTestAccounts: filters.filterTestAccounts,
    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
})

export const overviewValue = (items: WebOverviewItem[], key: string): number | null =>
    items.find((item) => item.key === key)?.value ?? null

/** Entry pages of sessions that an AI assistant referred, counted once per session. */
export const aiTrafficLandedPagesQuery = (filters: AiTrafficFilters): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query: `SELECT session.$entry_pathname AS page, uniq($session_id) AS sessions
FROM events
WHERE and(${AI_VIEW}, {filters})
GROUP BY page
HAVING page != ''
ORDER BY sessions DESC, page
LIMIT ${AI_TRAFFIC_TOP_LANDED_PAGES}`,
    filters: {
        dateRange: { date_from: filters.dateFrom, date_to: filters.dateTo },
        filterTestAccounts: filters.filterTestAccounts,
    },
    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
})

export interface AiTrafficWindow {
    /** Inclusive bounds as 'YYYY-MM-DD HH:mm:ss' in the project's timezone. */
    start: string
    end: string
}

export const resolveAiTrafficWindow = (
    range: AiTrafficDateRange,
    timezone: string,
    now: dayjs.Dayjs = dayjs().tz(timezone)
): AiTrafficWindow => {
    const from = range.dateFrom === 'all' ? null : dateStringToDayJs(range.dateFrom, timezone)
    const parsedTo = dateStringToDayJs(range.dateTo, timezone)
    // A bare date means the whole of that day, the way the date picker and the web analytics queries read it.
    const to = parsedTo && /^\d{4}-\d{2}-\d{2}$/.test(range.dateTo ?? '') ? parsedTo.endOf('day') : (parsedTo ?? now)
    const format = 'YYYY-MM-DD HH:mm:ss'
    return { start: from ? from.format(format) : '1970-01-01 00:00:00', end: to.format(format) }
}

/** Our own pages that the engines cited in checks inside the window, with how many answers cited each. */
export const aiTrafficCitedPagesQuery = (window: AiTrafficWindow): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query: `SELECT path(url) AS page, uniq(id) AS answers
FROM (
    SELECT id, arrayJoin(JSONExtract(target_urls, 'Array(String)')) AS url
    FROM system.aeo_citation_checks
    WHERE created_at >= toDateTime({window_start}) AND created_at <= toDateTime({window_end}) AND NOT check_failed
)
GROUP BY page
ORDER BY answers DESC, page
LIMIT ${AI_TRAFFIC_TOP_CITED_PAGES}`,
    values: { window_start: window.start, window_end: window.end },
})

export const parseCitedPages = (results: unknown[] | undefined): CitedPage[] =>
    (results ?? []).flatMap((row) =>
        Array.isArray(row) && typeof row[0] === 'string' ? [{ path: row[0], answers: Number(row[1] ?? 0) }] : []
    )

export const parseLandedPages = (results: unknown[] | undefined): LandedPage[] =>
    (results ?? []).flatMap((row) =>
        Array.isArray(row) && typeof row[0] === 'string' && row[0] !== ''
            ? [{ path: row[0], sessions: Number(row[1] ?? 0) }]
            : []
    )
