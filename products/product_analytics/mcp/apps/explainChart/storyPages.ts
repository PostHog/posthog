import type { ExplainChartData, StoryChapter } from './explainChartTypes'
import { anchorOf, chapterFacts, overviewFacts, type StoryFactsOptions } from './storyFacts'
import { funnelChapterFacts, funnelFactsSteps, funnelOverviewFacts } from './storyFunnelFacts'

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

interface StoryFacts {
    pointCount: number
    overview: string
    anchor: (range: [number, number]) => number
    chapter: (range: [number, number]) => string
}

function factsOf(data: ExplainChartData, formatValue: StoryFactsOptions['formatValue']): StoryFacts {
    if (data.shape === 'funnel_steps') {
        const steps = funnelFactsSteps(data)
        return {
            pointCount: steps.length,
            overview: funnelOverviewFacts(steps, formatValue),
            // The marker sits on the step that people reached, or failed to reach.
            anchor: ([, end]) => end,
            chapter: (range) => funnelChapterFacts(steps, range, formatValue),
        }
    }
    const series = data.results[data.seriesIndex]
    const values = series?.data ?? []
    const days = series?.days ?? []
    const options: StoryFactsOptions = {
        interval: data.query.interval ?? 'day',
        lastPointInProgress: data.lastPointInProgress,
        formatValue,
    }
    return {
        pointCount: values.length,
        overview: overviewFacts(values, options),
        anchor: (range) => anchorOf(values, range, options),
        chapter: (range) => chapterFacts(values, days, range, options),
    }
}

export function buildStoryPages(data: ExplainChartData, formatValue: StoryFactsOptions['formatValue']): StoryPage[] {
    const facts = factsOf(data, formatValue)
    const summary: StoryPage = {
        title: SUMMARY_TITLE,
        range: null,
        anchor: null,
        facts: facts.overview,
        chapter: null,
    }
    const chapters = data.chapters.map((chapter): StoryPage => {
        const range = isPointRange(chapter.range, facts.pointCount) ? chapter.range : null
        return {
            title: chapter.title,
            range,
            anchor: range ? facts.anchor(range) : null,
            facts: range ? facts.chapter(range) : '',
            chapter,
        }
    })
    // Numbered in chart order, so the markers read left to right. A chapter with no point comes last.
    const startOf = (page: StoryPage): number => page.range?.[0] ?? facts.pointCount
    return [summary, ...chapters.sort((a, b) => startOf(a) - startOf(b))]
}
