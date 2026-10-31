import type { insightLogicValues } from 'scenes/insights/insightLogic'

import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'
import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
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
    return isExplainChartData(output) ? output : null
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
        typeof output.headline === 'string' &&
        Array.isArray(output.chapters) &&
        Array.isArray(output.results) &&
        typeof output.seriesIndex === 'number' &&
        typeof output.query === 'object' &&
        output.query !== null
    )
}
