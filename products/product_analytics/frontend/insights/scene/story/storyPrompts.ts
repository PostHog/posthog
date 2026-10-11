import type { IntervalType } from '~/types'

import { quotedOneLine } from '../promptText'
import type { ChartMoment } from './chartMoments'
import type { MomentEvidence } from './momentEvidence'
import { plainStoryText } from './storyMarks'

const MAX_QUERY_LENGTH = 2000

export interface StoryPromptContext {
    insightUrl: string | null
    /** The chart's query as JSON, so an agent can run it when the insight has no link yet. */
    query: string | null
    seriesLabel: string
    interval: IntervalType
}

export function momentPrompt(moment: ChartMoment, evidence: MomentEvidence[], context: StoryPromptContext): string {
    // A breakdown value is whatever an SDK sent. Each finding stays on one line so it cannot add lines of its own.
    const found = evidence.map((item) => `- ${quotedOneLine(plainStoryText(item.text), 400)}`)
    return [
        'Help me understand one part of a PostHog insight.',
        '',
        `Insight: ${context.insightUrl ?? 'not saved yet, so it has no link'}`,
        `Series: ${quotedOneLine(context.seriesLabel)}, by ${context.interval}`,
        ...(context.query ? [`The chart's query: ${context.query.slice(0, MAX_QUERY_LENGTH)}`] : []),
        `The part I am looking at: ${moment.title}. ${plainStoryText(moment.summary)}`,
        ...(found.length ? ['', 'What PostHog already found:', ...found] : []),
        '',
        'Find the most likely cause. Look at who was behind it, where they came from, what was released or annotated around then, and whether tracking changed. If you can query PostHog, for example through the PostHog MCP server, run the queries yourself.',
        '',
        'Say how sure you are, and give me the query behind each claim so I can check it.',
    ].join('\n')
}
