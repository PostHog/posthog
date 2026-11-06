import type { z } from 'zod'

import { PostHogApiError } from '@/lib/errors'
import { ExplainChartSaveInputSchema } from '@/schema/tool-inputs'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type ToolBase } from '@/tools/types'

import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { storySeriesLabel } from 'products/product_analytics/mcp/apps/explainChart/storySeries'

import { buildExplanation } from './explainChart'

const schema = ExplainChartSaveInputSchema

type Params = z.infer<typeof schema>

type Result = {
    explanationId: string | null
    _posthogUrl?: string
    [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: string
}

const NOT_LINKABLE =
    'This chart has no saved insight that shows the explanation beside it, so there is no link. Give the findings in text.'

// The page builds PostHog links from the query or insight id, so only GitHub links are stored.
function storedExplanation(data: ExplainChartData): ExplainChartData {
    return {
        ...data,
        results: data.results.map((result, index) =>
            index === data.seriesIndex
                ? { ...result, label: storySeriesLabel(result.label) }
                : { label: storySeriesLabel(result.label) }
        ),
        chapters: data.chapters.map((chapter) => ({
            ...chapter,
            evidence: chapter.evidence.map((item) =>
                item.query || item.insightShortId ? { ...item, url: null } : item
            ),
        })),
    }
}

function isNotFound(error: unknown): boolean {
    return error instanceof PostHogApiError && error.status === 404
}

function notSaved(reason: string): Result {
    return {
        explanationId: null,
        [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: `The explanation was not saved, so there is no link to it. Give the findings in text and tell the person why: ${reason}`,
    }
}

export const explainChartSaveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { projectId, baseUrl, chart, data } = await buildExplanation(context, params)
    if (chart.linkableInsightId === null) {
        return { explanationId: null, [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: NOT_LINKABLE }
    }
    const insightId = chart.linkableInsightId
    const insights = context.api.insights({ projectId })
    const stored = storedExplanation(data)
    try {
        const updated = params.explanationId
            ? await insights.updateExplanation({ insightId, explanationId: params.explanationId, data: stored })
            : null
        // An id from another chart or another person is not found, so that fix becomes a new explanation.
        const saved =
            updated && (updated.success || !isNotFound(updated.error))
                ? updated
                : await insights.saveExplanation({ insightId, data: stored })
        if (!saved.success) {
            return notSaved(saved.error.message)
        }
        const url = `${baseUrl}${chart.path}?explanation=${saved.data.id}`
        return {
            explanationId: saved.data.id,
            _posthogUrl: url,
            [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: [
                `Give the person this link, which opens the explanation beside the chart in PostHog: ${url}`,
                `To fix this explanation, call explain-chart-save again with explanationId "${saved.data.id}", so the link shows the fix.`,
            ].join(' '),
        }
    } catch (error) {
        return notSaved(error instanceof Error ? error.message : String(error))
    }
}

export default (): ToolBase<typeof schema, Result> => ({
    name: 'explain-chart-save',
    schema,
    handler: explainChartSaveHandler,
})
