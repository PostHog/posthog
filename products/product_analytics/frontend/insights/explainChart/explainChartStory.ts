import type { insightLogicValues } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import type { AttachedContextItem } from '~/layout/ai/attachedContext'
import type { Node } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'

import type {
    ExplainChartData,
    StorySeriesResult,
} from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { storyEvidenceNode } from 'products/product_analytics/mcp/apps/explainChart/storyEvidenceNode'
import type { StoryPage } from 'products/product_analytics/mcp/apps/explainChart/storyPages'

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
    return isExplainChartData(output) ? { ...output, shape: 'time_series' } : null
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
    story: ExplainChartData,
    results: StorySeriesResult[],
    chartIndex: number | null,
    lastPointInProgress: boolean
): ExplainChartData {
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

function isExplainChartData(
    output: Record<string, unknown> | null
): output is ExplainChartData & Record<string, unknown> {
    return (
        !!output &&
        (output.shape === undefined || output.shape === 'time_series') &&
        typeof output.headline === 'string' &&
        Array.isArray(output.chapters) &&
        Array.isArray(output.results) &&
        typeof output.seriesIndex === 'number' &&
        typeof output.query === 'object' &&
        output.query !== null
    )
}
