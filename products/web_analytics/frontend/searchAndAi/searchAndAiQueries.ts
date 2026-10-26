import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'
import { percentage } from 'lib/utils/numbers'
import type { DateFilterState } from 'scenes/web-analytics/webAnalyticsLogic'

import { CompareFilter } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeHogQLString } from '~/queries/utils'

export const PAGE_PERFORMANCE_EVENTS = "('$pageview', '$screen', '$http_log')"

export const HUMAN_EVENTS = "('$pageview', '$screen')"

export const HUMAN_VIEW = "(event = '$pageview' OR event = '$screen') AND NOT `$virt_is_bot`"

export const GOOGLE_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'Organic Search' AND session.$entry_referring_domain ILIKE '%google%'`

export const AI_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'AI'`

export const CRAWLER =
    "`$virt_is_bot` = true AND `$virt_bot_name` != '' AND `$virt_traffic_category` IN ('ai_crawler', 'ai_assistant', 'ai_search')"

export type PagePerformanceMetric = 'llm_referrals' | 'agent_crawls' | 'google_search'

export interface PagePerformanceWindow {
    currentFrom: dayjs.Dayjs | null
    currentTo: dayjs.Dayjs
    previousFrom: dayjs.Dayjs | null
    previousTo: dayjs.Dayjs | null
    timezone: string
}

export const tsLiteral = (date: dayjs.Dayjs, timezone: string): string =>
    date.tz(timezone).format("'YYYY-MM-DD HH:mm:ss'")

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
    now: dayjs.Dayjs = dayjs().tz(timezone)
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

export const buildGoogleSearchConsoleQuery = (
    tableName: string,
    page: string,
    window: PagePerformanceWindow,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
): string => {
    const gscPath = buildPagePerformancePathExpr('path(page)', isPathCleaningEnabled, pathCleaningFilters)
    const gscPageKey = `concat(domain(page), ${gscPath})`
    const dateField = 'toDate(date)'
    const dateUpperBound = `${dateField} <= toDate(${tsLiteral(window.currentTo, window.timezone)})`
    const datePredicate = window.currentFrom
        ? `${dateField} >= toDate(${tsLiteral(window.currentFrom, window.timezone)}) AND ${dateUpperBound}`
        : dateUpperBound

    return `SELECT query AS "Query", sum(clicks) AS "Clicks", round(avg(position), 1) AS "Avg. position"
FROM ${escapeDottedHogQLIdentifier(tableName)}
WHERE ${gscPageKey} = ${escapeHogQLString(page)} AND (${datePredicate})
GROUP BY query
ORDER BY sum(clicks) DESC
LIMIT 20`
}
