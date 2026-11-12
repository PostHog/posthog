import type { insightLogicValues } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import type { AttachedContextItem } from '~/layout/ai/attachedContext'
import type { Node } from '~/queries/schema/schema-general'
import type { FunnelStep, InsightShortId } from '~/types'

import { hasBreakdown } from 'products/product_analytics/frontend/insights/funnels/funnelUtils'
import type {
    ExplainChartData,
    FunnelStepsExplainChartData,
    StorySeriesResult,
    TimeSeriesExplainChartData,
} from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { storyEvidenceNode } from 'products/product_analytics/mcp/apps/explainChart/storyEvidenceNode'
import type { StoryPage } from 'products/product_analytics/mcp/apps/explainChart/storyPages'
import { funnelBreakdownLabel, storySeriesLabel } from 'products/product_analytics/mcp/apps/explainChart/storySeries'

const INSIGHT_ID_KEYS = ['insightId', 'insight_id', 'id', 'short_id', 'shortId']

export function explainChartStoryFor(
    insight: insightLogicValues['insight'],
    input: Record<string, unknown> | null,
    output: Record<string, unknown> | null
): ExplainChartData | null {
    const insightIds = [insight.short_id, insight.id].filter((id) => id !== undefined && id !== null).map(String)
    const requested = INSIGHT_ID_KEYS.map((key) => input?.[key]).find((id) => id !== undefined && id !== null)
    if (requested === undefined || !insightIds.includes(String(requested))) {
        return null
    }
    if (isFunnelStepsData(output)) {
        return output
    }
    return isTimeSeriesData(output) ? { ...output, shape: 'time_series' } : null
}

export function withEvidenceLinks(story: ExplainChartData): ExplainChartData {
    return {
        ...story,
        chapters: story.chapters.map((chapter) => ({
            ...chapter,
            evidence: chapter.evidence.map((item) => ({
                ...item,
                url: item.query
                    ? evidenceInsightUrl(item.query)
                    : item.insightShortId
                      ? urls.insightView(item.insightShortId as InsightShortId)
                      : (item.url ?? null),
            })),
        })),
    }
}

function evidenceInsightUrl(query: Record<string, unknown>): string {
    return urls.insightNew({ query: storyEvidenceNode(query) as unknown as Node })
}

export function storyOnChart(
    story: TimeSeriesExplainChartData,
    results: StorySeriesResult[],
    chartIndex: number | null,
    lastPointInProgress: boolean
): TimeSeriesExplainChartData {
    if (!results.length) {
        return story
    }
    const chartDays = chartIndex === null ? undefined : results[chartIndex]?.days
    if (chartIndex === null || !chartDays) {
        return { ...story, chapters: story.chapters.map((chapter) => ({ ...chapter, range: null })) }
    }
    const savedDays = story.results[story.seriesIndex]?.days ?? []
    const dayIndex = new Map(chartDays.map((day, index) => [day, index]))
    return {
        ...story,
        results,
        seriesIndex: chartIndex,
        lastPointInProgress: lastPointInProgress && results[chartIndex].compare_label !== 'previous',
        chapters: story.chapters.map((chapter) => {
            const start = chapter.range ? dayIndex.get(savedDays[chapter.range[0]]) : undefined
            const end = chapter.range ? dayIndex.get(savedDays[chapter.range[1]]) : undefined
            return { ...chapter, range: start !== undefined && end !== undefined ? [start, end] : null }
        }),
    }
}

type FunnelChartBar = Pick<FunnelStep, 'count' | 'breakdown_value' | 'compare_label'>

export interface FunnelChartStep extends FunnelChartBar {
    nested_breakdown?: FunnelChartBar[]
}

// The chart draws a baseline before the breakdown values, sorts them and hides some, so the saved index does not find the bars.
export function followedFunnelBarIndex(story: FunnelStepsExplainChartData, steps: FunnelChartStep[]): number | null {
    const bars = steps[0]?.nested_breakdown
    if (!bars) {
        return steps.length ? 0 : null
    }
    const label = storySeriesLabel(story.breakdowns[story.seriesIndex])
    const matches = bars.flatMap((bar, index) =>
        bar.compare_label !== 'previous' &&
        (label === undefined ||
            (hasBreakdown(bar.breakdown_value) &&
                storySeriesLabel(funnelBreakdownLabel(bar.breakdown_value)) === label))
            ? [index]
            : []
    )
    return matches.length === 1 ? matches[0] : null
}

export function funnelStoryOnChart(
    story: FunnelStepsExplainChartData,
    steps: FunnelChartStep[],
    barIndex: number | null
): FunnelStepsExplainChartData {
    if (!steps.length) {
        return story
    }
    if (barIndex === null || steps.length !== story.steps.length) {
        return { ...story, chapters: story.chapters.map((chapter) => ({ ...chapter, range: null })) }
    }
    return {
        ...story,
        steps: story.steps.map((step, index) => {
            const chartStep = steps[index]
            const bar = chartStep.nested_breakdown ? chartStep.nested_breakdown[barIndex] : chartStep
            return { ...step, count: bar?.count ?? 0 }
        }),
    }
}

export function followUpContextFor(
    insight: insightLogicValues['insight'],
    page: StoryPage,
    step: number
): AttachedContextItem {
    const name = insight.name || insight.derived_name || 'this chart'
    const parts = [
        `Step ${step} of the chart explanation for the "${name}" insight (${insight.short_id}): ${page.title}.`,
        page.facts,
        page.chapter?.summary,
        page.chapter?.cause && `Likely cause: ${page.chapter.cause}`,
    ]
    return {
        type: 'text',
        label: `Step ${step}: ${page.title}`,
        value: parts.filter(Boolean).join(' '),
    }
}

function hasStoryBase(output: Record<string, unknown> | null): output is Record<string, unknown> {
    return (
        !!output &&
        typeof output.headline === 'string' &&
        Array.isArray(output.chapters) &&
        typeof output.seriesIndex === 'number' &&
        typeof output.query === 'object' &&
        output.query !== null
    )
}

function isTimeSeriesData(
    output: Record<string, unknown> | null
): output is TimeSeriesExplainChartData & Record<string, unknown> {
    return (
        hasStoryBase(output) &&
        (output.shape === undefined || output.shape === 'time_series') &&
        Array.isArray(output.results)
    )
}

function isFunnelStepsData(
    output: Record<string, unknown> | null
): output is FunnelStepsExplainChartData & Record<string, unknown> {
    return (
        hasStoryBase(output) &&
        output.shape === 'funnel_steps' &&
        Array.isArray(output.steps) &&
        Array.isArray(output.breakdowns)
    )
}
