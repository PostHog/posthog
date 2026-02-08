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

/** [avgPositive, avgNeutral, avgNegative, count, maxPositive, maxNegative] */
export type SentimentScores = [number, number, number, number, number, number]

/** Average sentiment scores across all $ai_sentiment events, plus max positive/negative from message-level scores. */
export function averageSentimentScores(events: LLMTraceEvent[]): SentimentScores | null {
    let totalPositive = 0
    let totalNeutral = 0
    let totalNegative = 0
    let maxPositive = 0
    let maxNegative = 0
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

        const eventMaxPos = event.properties.$ai_sentiment_positive_max_score ?? scores.positive ?? 0
        const eventMaxNeg = event.properties.$ai_sentiment_negative_max_score ?? scores.negative ?? 0
        if (eventMaxPos > maxPositive) {
            maxPositive = eventMaxPos
        }
        if (eventMaxNeg > maxNegative) {
            maxNegative = eventMaxNeg
        }
        count++
    }

    if (count === 0) {
        return null
    }

    return [totalPositive / count, totalNeutral / count, totalNegative / count, count, maxPositive, maxNegative]
}
