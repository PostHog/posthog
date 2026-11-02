import type { insightLogicValues } from 'scenes/insights/insightLogic'

import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'

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
