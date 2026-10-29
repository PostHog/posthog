import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'
import { percentage } from 'lib/utils/numbers'
import { BOT_ANALYTICS_EVENTS, WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import type { DateFilterState } from 'scenes/web-analytics/webAnalyticsLogic'

import { performQuery } from '~/queries/query'
import {
    BreakdownFilter,
    CompareFilter,
    DataTableNode,
    EventsNode,
    GroupNode,
    HogQLQuery,
    InsightVizNode,
    NodeKind,
    RefreshType,
    TrendsQuery,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeHogQLString } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import type { AiAssistantRow } from './AiAssistantList'

export const PAGE_PERFORMANCE_EVENTS = "('$pageview', '$screen', '$http_log')"

export const HUMAN_EVENTS = "('$pageview', '$screen')"

export const HUMAN_VIEW = "(event = '$pageview' OR event = '$screen') AND NOT `$virt_is_bot`"

export const GOOGLE_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'Organic Search' AND session.$entry_referring_domain ILIKE '%google%'`

export const AI_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'AI'`

export const CRAWLER =
    "`$virt_is_bot` = true AND `$virt_bot_name` != '' AND `$virt_traffic_category` IN ('ai_crawler', 'ai_assistant', 'ai_search')"

export const AI_CHANNEL_FILTER: WebAnalyticsPropertyFilters[number] = {
    key: '$channel_type',
    value: ['AI'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Session,
}

export const AI_CRAWLER_FILTERS: WebAnalyticsPropertyFilters = [
    { key: '$virt_is_bot', value: ['true'], operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
    { key: '$virt_bot_name', value: [''], operator: PropertyOperator.IsNot, type: PropertyFilterType.Event },
    {
        key: '$virt_traffic_category',
        value: ['ai_crawler', 'ai_assistant', 'ai_search'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    },
]

export const aiCrawlerRequestSeries = (customName: string): GroupNode => ({
    kind: NodeKind.GroupNode,
    name: BOT_ANALYTICS_EVENTS.join(', '),
    custom_name: customName,
    operator: FilterLogicalOperator.Or,
    nodes: BOT_ANALYTICS_EVENTS.map(
        (event): EventsNode => ({
            event,
            kind: NodeKind.EventsNode,
            math: BaseMathType.TotalCount,
            name: event,
        })
    ),
    math: BaseMathType.TotalCount,
})

export type PagePerformanceMetric = 'llm_referrals' | 'agent_crawls' | 'google_search'

export interface PagePerformanceWindow {
    currentFrom: dayjs.Dayjs | null
    currentTo: dayjs.Dayjs
    previousFrom: dayjs.Dayjs | null
    previousTo: dayjs.Dayjs | null
    timezone: string
}

const tsLiteral = (date: dayjs.Dayjs, timezone: string): string => date.tz(timezone).format("'YYYY-MM-DD HH:mm:ss'")

export const RAW_PATH = 'properties.$pathname'

export const buildPagePerformancePathExpr = (
    source: string,
    enabled: boolean,
    filters: { regex?: string; alias?: string }[] | undefined
): string => {
    if (!enabled || !filters?.length) {
        return source
    }
    let expr = source
    for (const f of filters) {
        if (f.regex && f.alias != null) {
            expr = `replaceRegexpAll(${expr}, ${escapeHogQLString(f.regex)}, ${escapeHogQLString(f.alias)})`
        }
    }
    return expr
}

export const resolvePagePerformanceWindow = (
    dateFilter: DateFilterState,
    compareFilter: CompareFilter,
    timezone: string,
    now: dayjs.Dayjs = dayjs().tz(timezone).startOf('minute')
): PagePerformanceWindow => {
    const currentFrom =
        dateFilter.dateFrom === 'all'
            ? null
            : (dateStringToDayJs(dateFilter.dateFrom, timezone) ?? now.subtract(7, 'day'))
    const parsedCurrentTo = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo, timezone) : null
    const currentTo =
        parsedCurrentTo && /^\d{4}-\d{2}-\d{2}$/.test(dateFilter.dateTo ?? '')
            ? parsedCurrentTo.endOf('day')
            : (parsedCurrentTo ?? now)

    if (!compareFilter.compare || !currentFrom) {
        return { currentFrom, currentTo, previousFrom: null, previousTo: null, timezone }
    }

    const spanMs = Math.max(currentTo.diff(currentFrom), 1)
    const compareToComponents = dateStringToComponents(compareFilter.compare_to ?? null)
    const previousFrom = compareToComponents
        ? componentsToDayJs(compareToComponents, currentFrom, timezone)
        : currentFrom.subtract(spanMs, 'millisecond')
    const previousTo = compareToComponents ? previousFrom.add(spanMs, 'millisecond') : currentFrom

    return { currentFrom, currentTo, previousFrom, previousTo, timezone }
}

/** Shares below 10% get a decimal, so a page holding 0.4% of site traffic doesn't read as 0%. */
export const formatShare = (part: number, whole: number): string | null => {
    if (whole <= 0 || part <= 0) {
        return null
    }
    const fraction = part / whole
    return percentage(fraction, fraction < 0.1 ? 1 : 0)
}

/** Percent change against the previous period, or null when there is no comparable baseline. */
export const changeVsPrevious = (current: number, previous: number): number | null => {
    if (previous === 0) {
        return null
    }
    return current === previous ? 0 : current / previous - 1
}

export const windowPredicates = (window: PagePerformanceWindow): { cur: string; prev: string; full: string } => {
    const upperBound = `timestamp <= ${tsLiteral(window.currentTo, window.timezone)}`
    const cur = window.currentFrom
        ? `timestamp >= ${tsLiteral(window.currentFrom, window.timezone)} AND ${upperBound}`
        : upperBound
    const prev =
        window.previousFrom && window.previousTo
            ? `timestamp >= ${tsLiteral(window.previousFrom, window.timezone)} AND timestamp < ${tsLiteral(window.previousTo, window.timezone)}`
            : 'false'
    return { cur, prev, full: `(${cur}) OR (${prev})` }
}

export const pageKeyExpr = (pathExpr: string): string => `concat(coalesce(properties.$host, ''), ${pathExpr})`

export const pageCandidatesPredicate = (pageKey: string, candidates: string[]): string =>
    candidates.length > 0 ? `${pageKey} IN (${candidates.map(escapeHogQLString).join(', ')})` : 'false'

export const buildBreakdownQuery = (
    metric: PagePerformanceMetric,
    page: string,
    window: PagePerformanceWindow,
    pathExpr: string
): string | null => {
    const { cur } = windowPredicates(window)
    const pageMatch = `${pageKeyExpr(pathExpr)} = ${escapeHogQLString(page)}`

    if (metric === 'llm_referrals') {
        return `
SELECT
    coalesce(nullIf(session.$entry_referring_domain, ''), '(direct)') AS "Assistant",
    uniq(person_id) AS "Visitors"
FROM events
WHERE and(${AI_VIEW}, ${pageMatch}, (${cur}), {filters})
GROUP BY "Assistant"
ORDER BY "Visitors" DESC
LIMIT 10
`
    }
    if (metric === 'agent_crawls') {
        return `
SELECT
    \`$virt_bot_name\` AS "Crawler",
    \`$virt_traffic_category\` AS "Category",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE and(${CRAWLER}, event IN ${PAGE_PERFORMANCE_EVENTS}, ${pageMatch}, (${cur}), {filters})
GROUP BY "Crawler", "Category"
ORDER BY "Requests" DESC
LIMIT 50
`
    }
    return null
}

const gscPageAndDatePredicate = (
    page: string,
    window: PagePerformanceWindow,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
): string => {
    const gscPath = buildPagePerformancePathExpr('path(page)', isPathCleaningEnabled, pathCleaningFilters)
    const dateField = 'toDate(date)'
    const dateUpperBound = `${dateField} <= toDate(${tsLiteral(window.currentTo, window.timezone)})`
    const datePredicate = window.currentFrom
        ? `${dateField} >= toDate(${tsLiteral(window.currentFrom, window.timezone)}) AND ${dateUpperBound}`
        : dateUpperBound
    return `concat(domain(page), ${gscPath}) = ${escapeHogQLString(page)} AND (${datePredicate})`
}

export const buildGoogleSearchConsoleQuery = (
    tableName: string,
    page: string,
    window: PagePerformanceWindow,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
): string =>
    `SELECT query AS "Query", sum(clicks) AS "Clicks", round(avg(position), 1) AS "Avg. position"
FROM ${escapeDottedHogQLIdentifier(tableName)}
WHERE ${gscPageAndDatePredicate(page, window, isPathCleaningEnabled, pathCleaningFilters)}
GROUP BY query
ORDER BY sum(clicks) DESC
LIMIT 20`

const AI_ASSISTANT_NAMES: [string[], string][] = [
    [['chatgpt', 'openai'], 'ChatGPT'],
    [['claude'], 'Claude'],
    [['perplexity'], 'Perplexity'],
    [['gemini', 'bard.google'], 'Gemini'],
    [['copilot'], 'Copilot'],
    [['grok'], 'Grok'],
    [['meta.ai'], 'Meta AI'],
    [['deepseek'], 'DeepSeek'],
    [['mistral'], 'Mistral'],
    [['kagi'], 'Kagi'],
    [['you.com'], 'You.com'],
    [['phind'], 'Phind'],
]

const AI_ASSISTANT_SOURCE =
    "if(lookupOrganicSourceType(session.$entry_utm_source) = 'AI', session.$entry_utm_source, session.$entry_referring_domain)"

const aiAssistantBranch = ([terms, name]: [string[], string]): string => {
    const condition = terms
        .map((term) => `positionCaseInsensitive(${AI_ASSISTANT_SOURCE}, ${escapeHogQLString(term)}) > 0`)
        .join(' OR ')
    return `${condition}, ${escapeHogQLString(name)}`
}

const AI_ASSISTANT_EXPR = `multiIf(${AI_ASSISTANT_NAMES.map(aiAssistantBranch).join(', ')}, coalesce(nullIf(nullIf(${AI_ASSISTANT_SOURCE}, ''), '$direct'), 'Unattributed'))`

export const AI_ASSISTANT_BREAKDOWN: BreakdownFilter = { breakdown: AI_ASSISTANT_EXPR, breakdown_type: 'hogql' }

export interface SearchAndAiTileFilters {
    dateFilter: DateFilterState
    filterTestAccounts: boolean
    properties: WebAnalyticsPropertyFilters
}

export const buildTrendTile = (
    { dateFilter, filterTestAccounts, properties }: SearchAndAiTileFilters,
    trend: Pick<TrendsQuery, 'series' | 'trendsFilter' | 'breakdownFilter'>
): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
        interval: dateFilter.interval,
        ...trend,
        properties,
        filterTestAccounts,
        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    },
    hidePersonsModal: true,
    embedded: true,
})

export const buildAiReferralTrendQuery = (
    filters: SearchAndAiTileFilters,
    breakdownFilter: BreakdownFilter | undefined
): InsightVizNode =>
    buildTrendTile(
        { ...filters, properties: [AI_CHANNEL_FILTER, ...filters.properties] },
        {
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview', math: BaseMathType.UniqueSessions },
            ],
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
            breakdownFilter,
        }
    )

export const buildAiCrawlerTrendQuery = (filters: SearchAndAiTileFilters, seriesName: string): InsightVizNode =>
    buildTrendTile(
        { ...filters, properties: [...AI_CRAWLER_FILTERS, ...filters.properties] },
        { series: [aiCrawlerRequestSeries(seriesName)], trendsFilter: { display: ChartDisplayType.ActionsLineGraph } }
    )

const GOOGLE_SEARCH_FILTERS: WebAnalyticsPropertyFilters = [
    {
        key: '$channel_type',
        value: ['Organic Search'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Session,
    },
    {
        key: '$entry_referring_domain',
        value: 'google',
        operator: PropertyOperator.IContains,
        type: PropertyFilterType.Session,
    },
]

export const buildGoogleSearchTrendQuery = (filters: SearchAndAiTileFilters): InsightVizNode =>
    buildTrendTile(
        { ...filters, properties: [...GOOGLE_SEARCH_FILTERS, ...filters.properties] },
        {
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    custom_name: 'Visitors from Google search',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        }
    )

export const buildAiReferralTableQuery = (
    {
        dateFilter,
        filterTestAccounts,
        properties,
        compareFilter,
        conversionGoal,
    }: SearchAndAiTileFilters & { compareFilter: CompareFilter; conversionGoal: WebAnalyticsConversionGoal | null },
    breakdownBy: WebStatsBreakdown
): DataTableNode => ({
    full: true,
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.WebStatsTableQuery,
        properties: [AI_CHANNEL_FILTER, ...properties],
        breakdownBy,
        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
        compareFilter,
        conversionGoal,
        limit: 10,
        filterTestAccounts,
        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    },
    embedded: false,
    showActions: true,
    columns: [
        'breakdown_value',
        'visitors',
        'views',
        ...(conversionGoal ? ['total_conversions', 'conversion_rate'] : []),
        'cross_sell',
    ],
})

const aiSessionsPredicate = (window: PagePerformanceWindow): string => {
    const lowerBound = window.currentFrom
        ? `$start_timestamp >= ${tsLiteral(window.currentFrom.subtract(1, 'day'), window.timezone)} AND `
        : ''
    const sessionWindow = `${lowerBound}$start_timestamp <= ${tsLiteral(window.currentTo, window.timezone)}`
    return `$session_id IN (SELECT session_id FROM sessions WHERE $channel_type = 'AI' AND ${sessionWindow})`
}

const buildAiAssistantsQuery = (window: PagePerformanceWindow, page: string | null, pathExpr: string): string => {
    const { cur } = windowPredicates(window)
    const pageMatch = page ? `${pageKeyExpr(pathExpr)} = ${escapeHogQLString(page)}` : 'true'
    return `
SELECT
    ${AI_ASSISTANT_EXPR} AS "Assistant",
    uniq(person_id) AS "Visitors",
    count() AS "Views"
FROM events
WHERE and(event IN ${HUMAN_EVENTS}, ${aiSessionsPredicate(window)}, ${pageMatch}, (${cur}), {filters})
GROUP BY "Assistant"
ORDER BY "Visitors" DESC
LIMIT 10
`
}

export const loadAiAssistantRows = async (
    {
        window,
        page,
        pathExpr,
        filterTestAccounts,
        properties,
    }: {
        window: PagePerformanceWindow
        page: string | null
        pathExpr: string
        filterTestAccounts: boolean
        properties: WebAnalyticsPropertyFilters
    },
    request?: { signal: AbortSignal; queryId: string; refresh?: RefreshType }
): Promise<AiAssistantRow[]> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: buildAiAssistantsQuery(window, page, pathExpr),
        filters: { filterTestAccounts, properties },
        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    }
    const response = await performQuery(query, { signal: request?.signal }, request?.refresh, request?.queryId)
    return (response.results ?? []).map((row: unknown[]) => ({
        assistant: String(row[0] ?? ''),
        visitors: Number(row[1] ?? 0),
        views: Number(row[2] ?? 0),
    }))
}

export interface GoogleSearchConsoleSummary {
    clicks: number
    impressions: number
    position: number | null
}

export const buildGoogleSearchConsoleSummaryQuery = (
    tableName: string,
    page: string,
    window: PagePerformanceWindow,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
): string =>
    `SELECT sum(clicks) AS clicks, sum(impressions) AS impressions, if(sum(impressions) > 0, sum(position * impressions) / sum(impressions), NULL) AS position
FROM ${escapeDottedHogQLIdentifier(tableName)}
WHERE ${gscPageAndDatePredicate(page, window, isPathCleaningEnabled, pathCleaningFilters)}`

export const GOOGLE_SEARCH_CONSOLE_TABLE_NAME = 'search_analytics_by_query_page'

export const findGoogleSearchConsoleTable = (tables: { name: string }[]): string | null =>
    tables.find((table) => table.name.includes(GOOGLE_SEARCH_CONSOLE_TABLE_NAME))?.name ?? null

export const GOOGLE_SEARCH_CONSOLE_DOCS_URL = 'https://posthog.com/docs/cdp/sources/google-search-console'
