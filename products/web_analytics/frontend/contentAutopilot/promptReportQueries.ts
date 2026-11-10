import { escapeRegex } from 'lib/utils/actions'

import {
    DataTableNode,
    DataVisualizationNode,
    DataWarehouseNode,
    HogQLQuery,
    InsightVizNode,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType } from '~/types'

import type { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { PromptVisibilityMetric } from './promptReport'
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
}

export const PROMPT_REPORT_TOP_SOURCES = 50
export const PROMPT_REPORT_TOP_CITATIONS = 20
export const PROMPT_REPORT_TOP_SEARCHES = 30
export const PROMPT_SET_TOP_SOURCES = 20

export const PROMPT_SOURCE_COLUMNS = ['domain', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_CITATION_COLUMNS = ['url', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_SEARCH_COLUMNS = ['query', 'searches', 'engines'] as const

// Every SQL query is answered checks inside the window, for one prompt or for the whole set. The prompt id and the
// window start travel as placeholder values, so the HogQL text never embeds user data.
const SET_WHERE = 'created_at >= toDateTime({window_start}) AND NOT check_failed'
const WHERE = `prompt_id = {prompt_id} AND ${SET_WHERE}`

const answered = (where: string): string => `(SELECT count() FROM system.aeo_citation_checks WHERE ${where})`

const hogql = (query: string, window: PromptReportWindow): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query,
    values: { prompt_id: window.promptId, window_start: `${window.from} 00:00:00` },
})

const setHogql = (query: string, window: PromptSetWindow): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query,
    values: {
        window_start: `${window.from} 00:00:00`,
        ...(window.branded !== 'all' && window.brandNames.length
            ? { brand_pattern: brandMentionPattern(window.brandNames) }
            : {}),
    },
})

/** RE2 pattern for `match()`: any brand name as a whole word, case folded by the caller. */
export const brandMentionPattern = (brandNames: string[]): string =>
    `\\b(${brandNames.map((name) => escapeRegex(name.toLowerCase())).join('|')})\\b`

const sqlString = (value: string): string => `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`

/** The engine's display name, so a chart legend reads "Claude" rather than its id. Unknown ids stay as they are. */
const ENGINE_NAME = `multiIf(${Object.entries(ENGINE_LABELS)
    .map(([engine, label]) => `engine = ${sqlString(engine)}, ${sqlString(label)}`)
    .join(', ')}, engine)`

const CHECKS_TABLE = 'system.aeo_citation_checks'

// Trends series take no placeholder values, so the brand pattern and the prompt id go into the filter text as
// escaped string literals.
const namesBrand = (field: string, brandNames: string[]): string =>
    `match(lower(${field}), ${sqlString(brandMentionPattern(brandNames))})`

const mentionedCondition = (brandNames: string[]): string =>
    brandNames.length ? `cited OR ${namesBrand("coalesce(answer_text, '')", brandNames)}` : 'cited'

/** Answered checks with every condition met, counted once each. */
const checksSeries = (conditions: string[]): DataWarehouseNode => ({
    kind: NodeKind.DataWarehouseNode,
    id: CHECKS_TABLE,
    table_name: CHECKS_TABLE,
    timestamp_field: 'timestamp',
    id_field: 'id',
    distinct_id_field: 'prompt_id',
    math: BaseMathType.TotalCount,
    properties: ['NOT check_failed', ...conditions].map((key) => ({ type: PropertyFilterType.HogQL, key })),
})

/** Daily share of the answered checks that meet `counted`, one line per engine, as a Trends insight so it opens,
 * saves and subscribes like any other. A day an engine did not run reads as 0%. */
const dailyRateChart = (conditions: string[], counted: string, from: string): InsightVizNode<TrendsQuery> => ({
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [checksSeries([...conditions, counted]), checksSeries(conditions)],
        interval: 'day',
        dateRange: { date_from: from, date_to: null, explicitDate: true },
        breakdownFilter: { breakdown_type: 'hogql', breakdown: ENGINE_NAME },
        trendsFilter: {
            display: ChartDisplayType.ActionsLineGraph,
            formula: 'A / B',
            aggregationAxisFormat: 'percentage_scaled',
            decimalPlaces: 0,
            showLegend: true,
        },
    },
    embedded: true,
    hidePersonsModal: true,
})

/** Daily citation (or brand mention) rate per engine for one prompt. */
export const promptVisibilityQuery = (
    window: PromptReportWindow,
    metric: PromptVisibilityMetric
): InsightVizNode<TrendsQuery> =>
    dailyRateChart(
        [`toString(prompt_id) = ${sqlString(window.promptId)}`],
        metric === 'mentioned' ? mentionedCondition(window.brandNames) : 'cited',
        window.from
    )

/** The set's checks on one side of the branded split, matching the API's `branded` filter. Without brand names no
 * prompt is branded. */
const setWhere = ({ branded, brandNames }: PromptSetWindow): string => {
    if (branded === 'all') {
        return SET_WHERE
    }
    if (!brandNames.length) {
        return branded === 'branded' ? `${SET_WHERE} AND false` : SET_WHERE
    }
    const namesBrandSql = 'match(lower(prompt_text), {brand_pattern})'
    return `${SET_WHERE} AND ${branded === 'branded' ? namesBrandSql : `NOT ${namesBrandSql}`}`
}

/** `setWhere` as Trends series filters. */
const segmentConditions = ({ branded, brandNames }: PromptSetWindow): string[] => {
    if (branded === 'all') {
        return []
    }
    if (!brandNames.length) {
        return branded === 'branded' ? ['false'] : []
    }
    const condition = namesBrand('prompt_text', brandNames)
    return [branded === 'branded' ? condition : `NOT ${condition}`]
}

/** Daily citation rate per engine across every prompt in the set. */
export const promptSetCitationQuery = (window: PromptSetWindow): InsightVizNode<TrendsQuery> =>
    dailyRateChart(segmentConditions(window), 'cited', window.from)

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
