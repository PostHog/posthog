import type { ExplainChartData } from './explainChartTypes'
import { storySeriesLabel } from './storySeries'

// The page builds PostHog links from the query or insight id, so only GitHub links are stored.
export function storedExplanation(data: ExplainChartData): ExplainChartData {
    const chart: ExplainChartData =
        data.shape === 'time_series'
            ? {
                  ...data,
                  results: data.results.map((result, index) =>
                      index === data.seriesIndex
                          ? { ...result, label: storySeriesLabel(result.label) }
                          : { label: storySeriesLabel(result.label) }
                  ),
              }
            : {
                  ...data,
                  steps: data.steps.map((step) => ({ ...step, name: storySeriesLabel(step.name) ?? '' })),
                  breakdowns: data.breakdowns.map((label) => storySeriesLabel(label) ?? ''),
              }
    return {
        ...chart,
        chapters: data.chapters.map((chapter) => ({
            ...chapter,
            evidence: chapter.evidence.map((item) =>
                item.query || item.insightShortId ? { ...item, url: null } : item
            ),
        })),
    }
}
