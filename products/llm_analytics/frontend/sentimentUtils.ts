/** Tight date window around trace creation for sentiment ClickHouse queries. */
export const SENTIMENT_DATE_WINDOW_DAYS = 2

export type SentimentLabel = 'positive' | 'neutral' | 'negative'

interface MessageScore {
    label?: string
    scores?: Record<string, number>
}

export function capitalize(s: string): string {
    return s[0].toUpperCase() + s.slice(1)
}

export function formatScore(score: number | undefined): string {
    if (score === undefined || score === null) {
        return '?'
    }
    return `${Math.round(score * 100)}%`
}

export function buildTagTooltip(
    label: string,
    scores?: { positive: number; neutral: number; negative: number }
): string {
    if (!scores) {
        return `Sentiment: ${label}`
    }
    return `Positive: ${formatScore(scores.positive)}\nNeutral: ${formatScore(scores.neutral)}\nNegative: ${formatScore(scores.negative)}`
}

export function computeExtremes(messages?: Record<string | number, MessageScore>): {
    maxPositive: number
    maxNegative: number
} {
    let maxPositive = 0
    let maxNegative = 0
    if (messages) {
        for (const msg of Object.values(messages)) {
            if (msg.label === 'positive' && msg.scores && msg.scores.positive > maxPositive) {
                maxPositive = msg.scores.positive
            }
            if (msg.label === 'negative' && msg.scores && msg.scores.negative > maxNegative) {
                maxNegative = msg.scores.negative
            }
        }
    }
    return { maxPositive, maxNegative }
}

/**
 * Extract plain text from message content, mirroring the backend's _extract_content_text.
 * Handles string content, Anthropic-style content block arrays, and nested structures.
 */
export function extractContentText(content: unknown): string {
    if (!content) {
        return ''
    }
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        return content
            .map((block) => {
                if (typeof block === 'string') {
                    return block
                }
                if (block && typeof block === 'object') {
                    if ('type' in block && block.type === 'text' && 'text' in block) {
                        return (block as { text: string }).text
                    }
                    if ('content' in block) {
                        return extractContentText((block as { content: unknown }).content)
                    }
                }
                return ''
            })
            .filter(Boolean)
            .join(' ')
    }
    return String(content)
}

export function buildSentimentBarTooltip(
    sentimentLabel: string,
    widthPercent: number,
    maxPositive: number,
    maxNegative: number
): string {
    const parts = [`${capitalize(sentimentLabel)}: ${widthPercent}%`]
    if (maxPositive > 0.05) {
        parts.push(`max positive: ${Math.round(maxPositive * 100)}%`)
    }
    if (maxNegative > 0.05) {
        parts.push(`max negative: ${Math.round(maxNegative * 100)}%`)
    }
    return parts.length > 1 ? `${parts[0]} (${parts.slice(1).join(', ')})` : parts[0]
}
