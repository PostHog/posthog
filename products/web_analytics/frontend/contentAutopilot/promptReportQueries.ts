import { escapeRegex } from 'lib/utils/actions'

import { DataTableNode, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { PromptOutcomeMetric, PromptVisibilityMetric } from './promptReport'
import { ENGINE_LABELS } from './utils'

export interface PromptReportWindow {
    promptId: string
    /** First day of the window, YYYY-MM-DD in the project's timezone. */
    from: string
    /** The words an answer must contain to count as a brand mention. */
    brandNames: string[]
}

export interface PromptSetWindow {
    /** First day of the window, YYYY-MM-DD in the project's timezone. */
    from: string
    /** The words a prompt must contain to count as branded. */
    brandNames: string[]
    /** Which checks to keep, by whether the prompt as it ran names the brand. */
    branded: BrandedSegmentEnumApi
    /** One engine's checks, or null for every engine. */
    engine: string | null
    /** The checks of one topic as the prompt had it when it ran, or null for every topic. */
    topic: string | null
}

export const PROMPT_REPORT_TOP_SOURCES = 50
export const PROMPT_REPORT_TOP_CITATIONS = 20
export const PROMPT_REPORT_TOP_SEARCHES = 30
export const PROMPT_SET_TOP_SOURCES = 20

export const PROMPT_SOURCE_COLUMNS = ['domain', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_CITATION_COLUMNS = ['url', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_SEARCH_COLUMNS = ['query', 'searches', 'engines'] as const

// Every query is answered web-search checks inside the window, for one prompt or for the whole set. No-search checks
// never cite, so they would pull every citation share down. The prompt id and the window start travel as placeholder
// values, so the HogQL text never embeds user data.
const SET_WHERE = "created_at >= toDateTime({window_start}) AND NOT check_failed AND mode = 'web_search'"
const WHERE = `prompt_id = {prompt_id} AND ${SET_WHERE}`

const answered = (where: string): string => `(SELECT count() FROM system.aeo_citation_checks WHERE ${where})`

const hogql = (query: string, window: PromptReportWindow, values: Record<string, string> = {}): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query,
    values: { prompt_id: window.promptId, window_start: `${window.from} 00:00:00`, ...values },
})

const setHogql = (query: string, window: PromptSetWindow): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query,
    values: {
        window_start: `${window.from} 00:00:00`,
        ...(window.brandNames.length ? { brand_pattern: brandMentionPattern(window.brandNames) } : {}),
        ...(window.engine !== null ? { engine: window.engine } : {}),
        ...(window.topic !== null ? { topic: window.topic } : {}),
    },
})

/** RE2 pattern for `match()`: any brand name as a whole word, case folded by the caller. */
export const brandMentionPattern = (brandNames: string[]): string =>
    `\\b(${brandNames.map((name) => escapeRegex(name.toLowerCase())).join('|')})\\b`

const mentionedExpr = (brandNames: string[]): string =>
    brandNames.length ? "cited OR match(lower(coalesce(answer_text, '')), {brand_pattern})" : 'cited'

const sqlString = (value: string): string => `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`

/** The engine's display name, so a chart legend reads "Claude" rather than its id. Unknown ids stay as they are. */
const ENGINE_NAME = `multiIf(${Object.entries(ENGINE_LABELS)
    .map(([engine, label]) => `engine = ${sqlString(engine)}, ${sqlString(label)}`)
    .join(', ')}, engine)`

// The label gets its own alias: naming it `engine` too would make the alias refer to itself.
const dailyValueSql = (where: string, value: string): string =>
    `SELECT toDate(created_at) AS day, ${ENGINE_NAME} AS engine_name, ${value} AS rate
FROM system.aeo_citation_checks
WHERE ${where}
GROUP BY day, engine_name
ORDER BY day, engine_name`

// Position is the mean rank of your first link over the answers that cite you, so other answers are left out.
const metricValue = (metric: PromptVisibilityMetric, brandNames: string[]): string =>
    metric === 'position'
        ? 'round(avgIf(target_best_position, cited), 1)'
        : `round(countIf(${metric === 'mentioned' ? mentionedExpr(brandNames) : 'cited'}) / count(), 3)`

const dailyMetricChart = (source: HogQLQuery, metric: PromptVisibilityMetric): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source,
    display: ChartDisplayType.ActionsLineGraph,
    chartSettings: {
        xAxis: { column: 'day' },
        yAxis: [
            {
                column: 'rate',
                settings: {
                    formatting: metric === 'position' ? { decimalPlaces: 1 } : { style: 'percent', decimalPlaces: 0 },
                },
            },
        ],
        seriesBreakdownColumn: 'engine_name',
        showLegend: true,
    },
})

/** Answers per day that cite you or mention you, stacked on the ones that don't, across every engine. */
export const promptOutcomeQuery = (window: PromptReportWindow, metric: PromptOutcomeMetric): DataVisualizationNode => {
    const met = metric === 'mentioned' ? mentionedExpr(window.brandNames) : 'cited'
    const [yes, no] = metric === 'mentioned' ? ['mentioned', 'not_mentioned'] : ['cited', 'not_cited']
    return {
        kind: NodeKind.DataVisualizationNode,
        source: hogql(
            `SELECT toDate(created_at) AS day, countIf(${met}) AS ${yes}, countIf(NOT (${met})) AS ${no}
FROM system.aeo_citation_checks
WHERE ${WHERE}
GROUP BY day
ORDER BY day`,
            window,
            metric === 'mentioned' && window.brandNames.length
                ? { brand_pattern: brandMentionPattern(window.brandNames) }
                : {}
        ),
        display: ChartDisplayType.ActionsStackedBar,
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [{ column: yes }, { column: no }],
            showLegend: true,
        },
    }
}

/** The set's checks on one side of the branded split, matching the API's `branded` filter. Without brand names no
 * prompt is branded. */
const segmentWhere = ({ branded, brandNames }: PromptSetWindow): string => {
    if (branded === 'all') {
        return SET_WHERE
    }
    if (!brandNames.length) {
        return branded === 'branded' ? `${SET_WHERE} AND false` : SET_WHERE
    }
    const namesBrand = 'match(lower(prompt_text), {brand_pattern})'
    return `${SET_WHERE} AND ${branded === 'branded' ? namesBrand : `NOT ${namesBrand}`}`
}

/** The set's checks narrowed the way the API's `branded`, `engine` and `topic` filters narrow them. */
const setWhere = (window: PromptSetWindow): string =>
    [
        segmentWhere(window),
        ...(window.engine !== null ? ['engine = {engine}'] : []),
        ...(window.topic !== null ? ['prompt_topic = {topic}'] : []),
    ].join(' AND ')

/** The same daily metric per engine across every prompt in the set. */
export const promptSetVisibilityQuery = (
    window: PromptSetWindow,
    metric: PromptVisibilityMetric
): DataVisualizationNode =>
    dailyMetricChart(setHogql(dailyValueSql(setWhere(window), metricValue(metric, window.brandNames)), window), metric)

const citedUrls = (where: string): string =>
    `SELECT id, engine, arrayJoin(JSONExtract(cited_urls, 'Array(String)')) AS url, target_urls
FROM system.aeo_citation_checks
WHERE ${where}`

const table = (source: HogQLQuery, columns: readonly string[]): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source,
    columns: [...columns],
    hiddenColumns: columns.includes('is_target') ? ['is_target'] : undefined,
    embedded: true,
    showActions: false,
    showOpenEditorButton: false,
})

const sourcesSql = (where: string, limit: number): string =>
    `SELECT domain(url) AS domain,
    uniq(id) AS answers,
    round(uniq(id) / ${answered(where)}, 3) AS share_of_answers,
    max(has(JSONExtract(target_urls, 'Array(String)'), url)) AS is_target
FROM (${citedUrls(where)})
WHERE domain != ''
GROUP BY domain
ORDER BY answers DESC, domain
LIMIT ${limit}`

/** Cited domains ranked by how many answers cited them, with the share of all answers that did. */
export const promptSourcesQuery = (window: PromptReportWindow): DataTableNode =>
    table(hogql(sourcesSql(WHERE, PROMPT_REPORT_TOP_SOURCES), window), PROMPT_SOURCE_COLUMNS)

/** The same ranking across every prompt in the set. */
export const promptSetSourcesQuery = (window: PromptSetWindow): DataTableNode =>
    table(setHogql(sourcesSql(setWhere(window), PROMPT_SET_TOP_SOURCES), window), PROMPT_SOURCE_COLUMNS)

/** Cited URLs ranked by how many answers cited them. */
export const promptCitationsQuery = (window: PromptReportWindow): DataTableNode =>
    table(
        hogql(
            `SELECT url,
    uniq(id) AS answers,
    round(uniq(id) / ${answered(WHERE)}, 3) AS share_of_answers,
    max(has(JSONExtract(target_urls, 'Array(String)'), url)) AS is_target
FROM (${citedUrls(WHERE)})
GROUP BY url
ORDER BY answers DESC, url
LIMIT ${PROMPT_REPORT_TOP_CITATIONS}`,
            window
        ),
        PROMPT_CITATION_COLUMNS
    )

/** The searches the engines ran, with how many answers ran each. Only engines that report their searches
 * contribute. Searches are lowercased with whitespace collapsed and counted once per answer, like the overview. */
export const promptSearchesQuery = (window: PromptReportWindow): DataTableNode =>
    table(
        hogql(
            `SELECT query, uniq(id) AS searches, uniq(engine) AS engines
FROM (SELECT id, engine,
        arrayJoin(arrayDistinct(arrayMap(
            q -> lower(trim(replaceRegexpAll(q, '[[:space:]]+', ' '))),
            JSONExtract(search_queries, 'Array(String)')
        ))) AS query
    FROM system.aeo_citation_checks
    WHERE ${WHERE})
WHERE query != ''
GROUP BY query
ORDER BY searches DESC, query
LIMIT ${PROMPT_REPORT_TOP_SEARCHES}`,
            window
        ),
        PROMPT_SEARCH_COLUMNS
    )

/** Scored answers per engine, split by how they speak about the brand. Unscored answers are left out. */
export const promptSentimentQuery = (window: PromptReportWindow): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source: hogql(
        `SELECT engine,
    multiIf(brand_sentiment = 'positive', 'Positive', brand_sentiment = 'negative', 'Negative', 'Neutral') AS sentiment,
    count() AS answers
FROM system.aeo_citation_checks
WHERE ${WHERE} AND brand_sentiment IS NOT NULL
GROUP BY engine, sentiment
ORDER BY engine, sentiment`,
        window
    ),
    display: ChartDisplayType.ActionsStackedBar,
    chartSettings: {
        xAxis: { column: 'engine' },
        yAxis: [{ column: 'answers' }],
        seriesBreakdownColumn: 'sentiment',
        showLegend: true,
    },
})
