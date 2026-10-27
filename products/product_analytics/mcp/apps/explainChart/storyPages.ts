import type { ExplainChartData, StoryChapter } from './explainChartTypes'
import { anchorOf, chapterFacts, overviewFacts, type StoryFactsOptions } from './storyFacts'

export interface StoryPage {
    title: string
    range: [number, number] | null
    anchor: number | null
    /** What the chart itself says, worked out here so that no number comes from the agent's text. */
    facts: string
    /** The agent's chapter. Null for the summary that opens the story. */
    chapter: StoryChapter | null
}

export const SUMMARY_TITLE = 'The big picture'

function isPointRange(range: [number, number] | null, length: number): range is [number, number] {
    if (!range) {
        return false
    }
    const [start, end] = range
    return Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start <= end && end < length
}

export function buildStoryPages(data: ExplainChartData, formatValue: StoryFactsOptions['formatValue']): StoryPage[] {
    const series = data.results[data.seriesIndex]
    const values = series?.data ?? []
    const days = series?.days ?? []
    const options: StoryFactsOptions = {
        interval: data.query.interval ?? 'day',
        lastPointInProgress: data.lastPointInProgress,
        formatValue,
    }
    const summary: StoryPage = {
        title: SUMMARY_TITLE,
        range: null,
        anchor: null,
        facts: overviewFacts(values, options),
        chapter: null,
    }
    const chapters = data.chapters.map((chapter): StoryPage => {
        const range = isPointRange(chapter.range, values.length) ? chapter.range : null
        return {
            title: chapter.title,
            range,
            anchor: range ? anchorOf(values, range, options) : null,
            facts: range ? chapterFacts(values, days, range, options) : '',
            chapter,
        }
    })
    // Numbered in date order, so the markers read left to right. A chapter with no point comes last.
    const startOf = (page: StoryPage): number => page.range?.[0] ?? values.length
    return [summary, ...chapters.sort((a, b) => startOf(a) - startOf(b))]
}
