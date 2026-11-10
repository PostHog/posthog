import type { z } from 'zod'

import { wrapError } from '@/lib/errors'
import { withUiApp } from '@/resources/ui-apps'
import { ExplainChartInputSchema } from '@/schema/tool-inputs'
import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'
import { applyProjectTestAccountDefault } from '@/tools/query-wrapper-factory'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type ToolBase } from '@/tools/types'

import type {
    ExplainChartData,
    FunnelStepsExplainChartData,
    StoryChapter,
    StoryEvidenceChartData,
    StoryFunnelsQuery,
    StorySeriesResult,
    StoryTrendsQuery,
    TimeSeriesExplainChartData,
} from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { sqlEvidenceChart } from 'products/product_analytics/mcp/apps/explainChart/sqlEvidenceChart'
import {
    insightPageShowsFunnelStory,
    insightPageShowsStory,
} from 'products/product_analytics/mcp/apps/explainChart/storyDisplays'
import { storyEvidenceNode } from 'products/product_analytics/mcp/apps/explainChart/storyEvidenceNode'
import { funnelBreakdownLabel } from 'products/product_analytics/mcp/apps/explainChart/storySeries'

import { analyzeQuery } from '../shared'
import { findStepRange, findStoryRange, lastBucketInProgress } from './storyRanges'

const schema = ExplainChartInputSchema

export type Params = z.infer<typeof schema>

type Result = ExplainChartData & { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: string }

const RENDERED_NOTE =
    'The person sees the chart explanation rendered inline: the chart, every chapter, each cause and each piece of evidence. Do not write any of that again in any form, not as a recap, a bullet list or a summary of the moments. Keep your reply short: which chapter to start with, only what the chart explanation cannot hold (a caveat about the data, a linked fix, a decision that is still open), and one next step you offer. If the person says the explanation did not load, give the findings in text.'

// The markers sit on one value over time. These displays draw that as they are.
const TIME_SERIES_DISPLAYS = new Set([
    'ActionsLineGraph',
    'ActionsLineGraphCumulative',
    'ActionsBar',
    'ActionsUnstackedBar',
    'ActionsAreaGraph',
    'ActionsStackedBar',
])

// These show a total over the range, so the explanation draws the line behind it. Any other display is refused.
const TOTAL_DISPLAYS = new Set([
    'Auto',
    'BoldNumber',
    'Metric',
    'ActionsPie',
    'ActionsDonut',
    'ActionsProportionBar',
    'ActionsBarValue',
    'ActionsTable',
    'WorldMap',
    'CalendarHeatmap',
    'SlopeGraph',
])

const NOT_SUPPORTED =
    'This tool explains trends charts and funnels that show steps. For other kinds, write the explanation in the chat instead.'
const NOT_OVER_TIME =
    'This tool explains a trends chart that shows one value over time, and this chart does not. Write the explanation in the chat instead.'
const NOT_FUNNEL_STEPS =
    'This tool explains a funnel that shows steps, and this one shows conversion over time or time to convert. Write the explanation in the chat instead.'

// The explanation redraws insight evidence through the query tool for its kind. A tool's schema is narrower than the
// query's, so evidence the tool would refuse keeps its link and no chart.
const REDRAW_TOOLS = new Map(
    (
        [
            ['TrendsQuery', 'query-trends'],
            ['FunnelsQuery', 'query-funnel'],
            ['RetentionQuery', 'query-retention'],
            ['StickinessQuery', 'query-stickiness'],
            ['PathsQuery', 'query-paths'],
            ['LifecycleQuery', 'query-lifecycle'],
        ] as const
    ).map(([kind, tool]) => [kind as string, { tool, schema: GENERATED_TOOLS[tool]!().schema }])
)

function redrawToolFor(query: Record<string, unknown> | undefined): string | null {
    // A trends query may leave out `kind`, which the trends tool fills in.
    const kind = query?.kind ?? 'TrendsQuery'
    const redraw = query && typeof kind === 'string' ? REDRAW_TOOLS.get(kind) : undefined
    return redraw && redraw.schema.safeParse(query).success ? redraw.tool : null
}

type SqlEvidence = { chart: StoryEvidenceChartData | null } | { error: string }

const SQL_EVIDENCE_TIME_LIMIT_MS = 60_000

function isSqlQuery(query: Record<string, unknown> | undefined): query is Record<string, unknown> {
    return query?.kind === 'HogQLQuery' && typeof query.query === 'string'
}

async function runSqlEvidence(
    context: Context,
    projectId: string,
    chapters: Params['chapters']
): Promise<Map<string, SqlEvidence>> {
    const queries = new Map<string, Record<string, unknown>>()
    for (const item of chapters.flatMap((chapter) => chapter.evidence ?? [])) {
        if (isSqlQuery(item.query)) {
            queries.set(JSON.stringify(item.query), item.query)
        }
    }
    // One at a time, so the evidence does not use up the team's concurrent query limit, within one shared time limit.
    const signal = AbortSignal.timeout(SQL_EVIDENCE_TIME_LIMIT_MS)
    const results = new Map<string, SqlEvidence>()
    for (const [key, query] of queries) {
        if (signal.aborted) {
            results.set(key, { error: 'it did not finish in time' })
            continue
        }
        try {
            const response = await context.api.query({ projectId }).runQuery({ query, signal })
            const columns = (response.columns ?? []).map(String)
            const rows = Array.isArray(response.results) ? (response.results as unknown[][]) : []
            results.set(key, { chart: sqlEvidenceChart(columns, rows) })
        } catch (error) {
            results.set(key, { error: error instanceof Error ? error.message : String(error) })
        }
    }
    return results
}

function sqlProblems(chapters: Params['chapters'], sqlEvidence: Map<string, SqlEvidence>): string[] {
    return chapters.flatMap((chapter) =>
        (chapter.evidence ?? []).flatMap((item) => {
            const result = isSqlQuery(item.query) ? sqlEvidence.get(JSON.stringify(item.query)) : undefined
            if (!result) {
                return []
            }
            if ('error' in result) {
                return [`The SQL behind "${item.text}" failed, so it shows as a link only: ${result.error}`]
            }
            return result.chart
                ? []
                : [
                      `The SQL behind "${item.text}" returned nothing to draw, so it shows as a link only. Select the x-axis column first, then either the numbers to draw, or one text column to break down by followed by one number.`,
                  ]
        })
    )
}

type StoryQuery = StoryTrendsQuery | StoryFunnelsQuery

export interface StoryChart {
    query: StoryQuery
    linkableInsightId: number | null
    insightName: string | null
    path: string
}

function asStoryQuery(query: unknown): StoryQuery {
    const inner = analyzeQuery(query).innerQuery
    if (inner?.kind === 'TrendsQuery') {
        return asTrendsQuery(inner)
    }
    if (inner?.kind === 'FunnelsQuery') {
        const funnel = { ...inner } as StoryFunnelsQuery
        const vizType = funnel.funnelsFilter?.funnelVizType
        if (vizType !== undefined && vizType !== null && vizType !== 'steps') {
            throw new Error(NOT_FUNNEL_STEPS)
        }
        return funnel
    }
    throw new Error(NOT_SUPPORTED)
}

function pageShowsStory(query: StoryQuery): boolean {
    return query.kind === 'FunnelsQuery'
        ? insightPageShowsFunnelStory(query.funnelsFilter)
        : insightPageShowsStory(query.trendsFilter?.display)
}

function asTrendsQuery(inner: object): StoryTrendsQuery {
    const trends = { ...inner } as StoryTrendsQuery
    const display = trends.trendsFilter?.display
    if (typeof display !== 'string' || TIME_SERIES_DISPLAYS.has(display)) {
        return trends
    }
    if (!TOTAL_DISPLAYS.has(display)) {
        throw new Error(NOT_OVER_TIME)
    }
    trends.trendsFilter = { ...trends.trendsFilter, display: 'ActionsLineGraph' }
    return trends
}

function newInsightPath(query: Record<string, unknown>): string {
    const node = storyEvidenceNode(query)
    const encoded = encodeURIComponent(JSON.stringify(node))
    // A new insight cannot show or edit SQL, so SQL opens in the SQL editor like `urls.insightNew()` does
    return (node.source as { kind?: unknown } | undefined)?.kind === 'HogQLQuery'
        ? `/sql?open_query=${encoded}`
        : `/insights/new#q=${encoded}`
}

async function loadChart(context: Context, projectId: string, params: Params): Promise<StoryChart> {
    if (params.insightId === undefined) {
        const query = asStoryQuery(params.query)
        await applyProjectTestAccountDefault(context, query)
        return { query, linkableInsightId: null, insightName: null, path: newInsightPath(query) }
    }
    const insight = await context.api.insights({ projectId }).get({ insightId: params.insightId })
    if (!insight.success) {
        throw wrapError(`Failed to get insight: ${insight.error.message}`, insight.error)
    }
    const savedQuery = analyzeQuery(insight.data.query).innerQuery as StoryQuery | undefined
    return {
        query: asStoryQuery(insight.data.query),
        linkableInsightId: savedQuery && pageShowsStory(savedQuery) ? insight.data.id : null,
        insightName: insight.data.name || insight.data.derived_name || null,
        path: `/insights/${insight.data.short_id}`,
    }
}

function warningMessages(warnings: unknown[]): string[] {
    return warnings.map((warning) =>
        typeof warning === 'string' ? warning : ((warning as { message?: string }).message ?? JSON.stringify(warning))
    )
}

function describeResult(built: BuiltExplanation, chapterCount: number): string {
    const { chart, seriesLabel, missed, warnings, evidenceProblems } = built
    const name = chart.insightName ?? seriesLabel ?? 'the chart'
    const lines = [`The explanation of "${name}" has ${chapterCount} chapters.`]
    if (chart.linkableInsightId !== null) {
        lines.push(
            'Where the person cannot see it rendered inline, call explain-chart-save with the same arguments for a link that opens it beside the chart in PostHog.'
        )
    }
    if (warnings.length) {
        lines.push(`The query came with warnings the person should hear about: ${warningMessages(warnings).join(' ')}`)
    }
    if (missed.length) {
        const titles = missed.map((title) => `"${title}"`).join(', ')
        const shows = missed.length === 1 ? 'that chapter shows' : 'those chapters show'
        lines.push(
            chart.query.kind === 'FunnelsQuery'
                ? `No step on the funnel matches ${titles}, so ${shows} without a highlight. Use step numbers, where 1 is the first step, and call this tool again.`
                : `No point on the chart matches the dates of ${titles}, so ${shows} without a highlight. Use dates from the chart's \`days\` and call this tool again.`
        )
    }
    lines.push(...evidenceProblems)
    return lines.join(' ')
}

export interface BuiltExplanation {
    projectId: string
    baseUrl: string
    chart: StoryChart
    seriesLabel: string | undefined
    data: ExplainChartData
    missed: string[]
    warnings: unknown[]
    evidenceProblems: string[]
}

type ChartBody =
    | Pick<TimeSeriesExplainChartData, 'shape' | 'query' | 'results' | 'lastPointInProgress'>
    | Pick<FunnelStepsExplainChartData, 'shape' | 'query' | 'steps' | 'breakdowns'>

interface ShownChart {
    body: ChartBody
    seriesLabel: string | undefined
    rangeOf: (start: string, end?: string) => [number, number] | null
}

function trendsChart(
    query: StoryTrendsQuery,
    results: StorySeriesResult[],
    seriesIndex: number,
    timezone: string | undefined
): ShownChart {
    const series = results[seriesIndex]
    if (!series?.data?.length) {
        throw new Error(
            results.length
                ? `The chart has ${results.length} series, so \`series\` must be below ${results.length}.`
                : 'The chart has no data to explain.'
        )
    }
    const interval = query.interval ?? 'day'
    const days = series.days ?? []
    return {
        body: {
            shape: 'time_series',
            query,
            results,
            lastPointInProgress: lastBucketInProgress(days, interval, timezone),
        },
        seriesLabel: series.label,
        rangeOf: (start, end) => findStoryRange(days, interval, start, end),
    }
}

interface FunnelStepResult {
    name?: string
    custom_name?: string | null
    count?: number
    breakdown_value?: unknown
    compare_label?: 'current' | 'previous'
}

function funnelChart(query: StoryFunnelsQuery, results: unknown[], seriesIndex: number): ShownChart {
    // A funnel with a breakdown returns one list of steps per breakdown value.
    // A comparison adds the previous period's steps to the same result, and the explanation follows the current period.
    const groups = ((Array.isArray(results[0]) ? results : [results]) as FunnelStepResult[][])
        .map((group) => group.filter((step) => step.compare_label !== 'previous'))
        .filter((group) => group.length > 0)
    const followed = groups[seriesIndex]
    if (!followed) {
        throw new Error(
            groups.length
                ? `The funnel has ${groups.length} breakdown values, so \`series\` must be below ${groups.length}.`
                : 'The funnel has no data to explain.'
        )
    }
    const steps = followed.map((step, index) => ({
        name: step.custom_name || step.name || `Step ${index + 1}`,
        count: step.count ?? 0,
    }))
    const breakdowns = groups.length > 1 ? groups.map((group) => funnelBreakdownLabel(group[0]?.breakdown_value)) : []
    return {
        body: { shape: 'funnel_steps', query, steps, breakdowns },
        seriesLabel: breakdowns[seriesIndex],
        rangeOf: (start, end) =>
            findStepRange(
                steps.map((step) => step.name),
                start,
                end
            ),
    }
}

export async function buildExplanation(context: Context, params: Params): Promise<BuiltExplanation> {
    const projectId = await context.stateManager.getProjectId()
    const chart = await loadChart(context, projectId, params)

    const response = await context.api.query({ projectId }).runQuery({ query: chart.query })
    const results = Array.isArray(response.results) ? (response.results as unknown[]) : []
    const { timezone, warnings = [] } = response as { timezone?: string; warnings?: unknown[] | null }
    const shown =
        chart.query.kind === 'FunnelsQuery'
            ? funnelChart(chart.query, results, params.series)
            : trendsChart(chart.query, results as StorySeriesResult[], params.series, timezone)

    const sqlEvidence = await runSqlEvidence(context, projectId, params.chapters)
    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const missed: string[] = []
    const chapters: StoryChapter[] = params.chapters.map((chapter) => {
        const range = shown.rangeOf(chapter.start, chapter.end)
        if (!range) {
            missed.push(chapter.title)
        }
        return {
            title: chapter.title,
            range,
            summary: chapter.summary ?? null,
            cause: chapter.cause ?? null,
            confidence: chapter.confidence ?? null,
            confidenceReason: chapter.confidence_reason ?? null,
            evidence: (chapter.evidence ?? []).map((item) => {
                const queryTool = redrawToolFor(item.query)
                const sql = isSqlQuery(item.query) ? sqlEvidence.get(JSON.stringify(item.query)) : undefined
                return {
                    text: item.text,
                    url: item.query
                        ? `${baseUrl}${newInsightPath(item.query)}`
                        : item.insightShortId
                          ? `${baseUrl}/insights/${item.insightShortId}`
                          : (item.url ?? null),
                    query: item.query ?? null,
                    insightShortId: item.insightShortId ?? null,
                    queryTool,
                    chart: sql && 'chart' in sql ? sql.chart : null,
                }
            }),
        }
    })

    const data: ExplainChartData = {
        ...shown.body,
        seriesIndex: params.series,
        insightName: chart.insightName,
        ...(warnings?.length ? { warnings } : {}),
        headline: params.headline,
        chapters,
    }
    return {
        projectId,
        baseUrl,
        chart,
        seriesLabel: shown.seriesLabel,
        data,
        missed,
        warnings: warnings ?? [],
        evidenceProblems: sqlProblems(params.chapters, sqlEvidence),
    }
}

export const explainChartHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const built = await buildExplanation(context, params)
    return {
        ...built.data,
        _posthogUrl: `${built.baseUrl}${built.chart.path}`,
        [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: describeResult(built, params.chapters.length),
    }
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('explain-chart', {
        name: 'explain-chart',
        schema,
        renderedNote: RENDERED_NOTE,
        handler: explainChartHandler,
    })
