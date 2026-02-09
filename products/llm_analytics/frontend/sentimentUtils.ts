import { LLMTraceEvent } from '~/queries/schema/schema-general'

export type SentimentLabel = 'positive' | 'neutral' | 'negative'

export const SENTIMENT_COLOR: Record<SentimentLabel, string> = {
    positive: 'bg-success',
    negative: 'bg-danger',
    neutral: 'bg-border',
}

export const SENTIMENT_SEVERITY: Record<SentimentLabel, number> = {
    negative: 3,
    neutral: 2,
    positive: 1,
}

export function getSentimentLabelFromScores(positive: number, neutral: number, negative: number): SentimentLabel {
    if (negative >= positive && negative >= neutral) {
        return 'negative'
    }
    if (positive >= neutral) {
        return 'positive'
    }
    return 'neutral'
}

export function findWorstSentimentEvent(events: LLMTraceEvent[]): LLMTraceEvent | null {
    let worst: LLMTraceEvent | null = null
    for (const event of events) {
        if (event.event !== '$ai_sentiment') {
            continue
        }
        const label = event.properties.$ai_sentiment_label as SentimentLabel | undefined
        if (
            !worst ||
            (SENTIMENT_SEVERITY[label!] ?? 0) >
                (SENTIMENT_SEVERITY[worst.properties.$ai_sentiment_label as SentimentLabel] ?? 0)
        ) {
            worst = event
        }
    }
    return worst
}
