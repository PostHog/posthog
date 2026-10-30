import { escapeRegex } from 'lib/utils/actions'

import { DataTableNode, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { PromptVisibilityMetric } from './promptReport'

export interface PromptReportWindow {
    promptId: string
    /** First day of the window, YYYY-MM-DD in the project's timezone. */
    from: string
    /** The words an answer must contain to count as a brand mention. */
    brandNames: string[]
}

export const PROMPT_REPORT_TOP_SOURCES = 50
export const PROMPT_REPORT_TOP_CITATIONS = 20
export const PROMPT_REPORT_TOP_SEARCHES = 30

export const PROMPT_SOURCE_COLUMNS = ['domain', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_CITATION_COLUMNS = ['url', 'answers', 'share_of_answers', 'is_target'] as const
export const PROMPT_SEARCH_COLUMNS = ['query', 'searches', 'engines'] as const

// Every query is one prompt's answered checks inside the window. The prompt id and the window start travel
// as placeholder values, so the HogQL text never embeds user data.
const WHERE = 'prompt_id = {prompt_id} AND created_at >= toDateTime({window_start}) AND NOT check_failed'

const ANSWERED = `(SELECT count() FROM system.aeo_citation_checks WHERE ${WHERE})`

const hogql = (query: string, window: PromptReportWindow, values: Record<string, string> = {}): HogQLQuery => ({
    kind: NodeKind.HogQLQuery,
    query,
    values: { prompt_id: window.promptId, window_start: `${window.from} 00:00:00`, ...values },
})

/** RE2 pattern for `match()`: any brand name as a whole word, case folded by the caller. */
export const brandMentionPattern = (brandNames: string[]): string =>
    `\\b(${brandNames.map((name) => escapeRegex(name.toLowerCase())).join('|')})\\b`

const mentionedExpr = (brandNames: string[]): string =>
    brandNames.length ? "cited OR match(lower(coalesce(answer_text, '')), {brand_pattern})" : 'cited'

/** Daily citation (or brand mention) rate per engine. Days an engine did not run are gaps, not zeros. */
export const promptVisibilityQuery = (
    window: PromptReportWindow,
    metric: PromptVisibilityMetric
): DataVisualizationNode => {
    const counted = metric === 'mentioned' ? mentionedExpr(window.brandNames) : 'cited'
    return {
        kind: NodeKind.DataVisualizationNode,
        source: hogql(
            `SELECT toDate(created_at) AS day, engine, round(countIf(${counted}) / count(), 3) AS rate
FROM system.aeo_citation_checks
WHERE ${WHERE}
GROUP BY day, engine
ORDER BY day, engine`,
            window,
            metric === 'mentioned' && window.brandNames.length
                ? { brand_pattern: brandMentionPattern(window.brandNames) }
                : {}
        ),
        display: ChartDisplayType.ActionsLineGraph,
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [{ column: 'rate', settings: { formatting: { style: 'percent', decimalPlaces: 0 } } }],
            seriesBreakdownColumn: 'engine',
            showLegend: true,
        },
    }
}

const citedUrls = `SELECT id, engine, arrayJoin(JSONExtract(cited_urls, 'Array(String)')) AS url, target_urls
FROM system.aeo_citation_checks
WHERE ${WHERE}`

const table = (source: HogQLQuery, columns: readonly string[]): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source,
    columns: [...columns],
    hiddenColumns: columns.includes('is_target') ? ['is_target'] : undefined,
    embedded: true,
    showActions: false,
    showOpenEditorButton: false,
})

/** Cited domains ranked by how many answers cited them, with the share of all answers that did. */
export const promptSourcesQuery = (window: PromptReportWindow): DataTableNode =>
    table(
        hogql(
            `SELECT domain(url) AS domain,
    uniq(id) AS answers,
    round(uniq(id) / ${ANSWERED}, 3) AS share_of_answers,
    max(has(JSONExtract(target_urls, 'Array(String)'), url)) AS is_target
FROM (${citedUrls})
WHERE domain != ''
GROUP BY domain
ORDER BY answers DESC, domain
LIMIT ${PROMPT_REPORT_TOP_SOURCES}`,
            window
        ),
        PROMPT_SOURCE_COLUMNS
    )

/** Cited URLs ranked by how many answers cited them. */
export const promptCitationsQuery = (window: PromptReportWindow): DataTableNode =>
    table(
        hogql(
            `SELECT url,
    uniq(id) AS answers,
    round(uniq(id) / ${ANSWERED}, 3) AS share_of_answers,
    max(has(JSONExtract(target_urls, 'Array(String)'), url)) AS is_target
FROM (${citedUrls})
GROUP BY url
ORDER BY answers DESC, url
LIMIT ${PROMPT_REPORT_TOP_CITATIONS}`,
            window
        ),
        PROMPT_CITATION_COLUMNS
    )

/** The searches the engines ran, with how often. Only engines that report their searches contribute. */
export const promptSearchesQuery = (window: PromptReportWindow): DataTableNode =>
    table(
        hogql(
            `SELECT query, count() AS searches, uniq(engine) AS engines
FROM (SELECT engine, arrayJoin(JSONExtract(search_queries, 'Array(String)')) AS query
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
