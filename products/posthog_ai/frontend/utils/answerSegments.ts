import { type AgentChartBlock, findAgentChartBlocks } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'

export type AnswerSegment = { type: 'markdown'; text: string } | { type: 'chart'; block: AgentChartBlock }

export function hasAnswerCharts(text: string | undefined): boolean {
    return !!text && findAgentChartBlocks(text).length > 0
}

/** Splits an answer into markdown runs and the chart blocks between them, in order. */
export function splitAnswerSegments(text: string): AnswerSegment[] {
    const segments: AnswerSegment[] = []
    let position = 0
    const pushMarkdown = (markdown: string): void => {
        if (markdown.trim()) {
            segments.push({ type: 'markdown', text: markdown })
        }
    }
    for (const block of findAgentChartBlocks(text)) {
        pushMarkdown(text.slice(position, block.start))
        segments.push({ type: 'chart', block })
        position = block.end
    }
    pushMarkdown(text.slice(position))
    return segments
}
