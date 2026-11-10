import type { StorySeriesResult, TimeSeriesExplainChartData } from './explainChartTypes'

export const STORY_SERIES_LABEL_MAX_LENGTH = 400

export function storySeriesLabel(label: string | undefined): string | undefined {
    return label?.slice(0, STORY_SERIES_LABEL_MAX_LENGTH)
}

// The tool and the insight page both name a breakdown value with this, so the page can find the followed value by name.
export function funnelBreakdownLabel(value: unknown): string {
    const text = Array.isArray(value) ? value.join(', ') : value === undefined || value === null ? '' : String(value)
    return text || 'None'
}

// Breakdown series are sorted by volume, so the saved index can point at another series by the time a link is opened.
export function followedSeriesIndex(story: TimeSeriesExplainChartData, results: StorySeriesResult[]): number | null {
    const label = story.results[story.seriesIndex]?.label
    if (label === undefined) {
        return results[story.seriesIndex] ? story.seriesIndex : null
    }
    const matches = results.flatMap((result, index) => (storySeriesLabel(result.label) === label ? [index] : []))
    if (matches.length === 1) {
        return matches[0] ?? null
    }
    return matches.includes(story.seriesIndex) ? story.seriesIndex : null
}
