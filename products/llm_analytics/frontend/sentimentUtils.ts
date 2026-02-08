import { LLMTraceEvent } from '~/queries/schema/schema-general'

export type SentimentLabel = 'positive' | 'neutral' | 'negative'

export const SENTIMENT_COLOR: Record<SentimentLabel, string> = {
    positive: 'bg-success',
    negative: 'bg-danger',
    neutral: 'bg-border',
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

/** Average sentiment scores across all $ai_sentiment events. Returns [positive, neutral, negative, count] tuple or null. */
export function averageSentimentScores(events: LLMTraceEvent[]): [number, number, number, number] | null {
    let totalPositive = 0
    let totalNeutral = 0
    let totalNegative = 0
    let count = 0

    for (const event of events) {
        if (event.event !== '$ai_sentiment') {
            continue
        }
        const scores = event.properties.$ai_sentiment_scores
        if (!scores) {
            continue
        }
        totalPositive += scores.positive ?? 0
        totalNeutral += scores.neutral ?? 0
        totalNegative += scores.negative ?? 0
        count++
    }

    if (count === 0) {
        return null
    }

    return [totalPositive / count, totalNeutral / count, totalNegative / count, count]
}
