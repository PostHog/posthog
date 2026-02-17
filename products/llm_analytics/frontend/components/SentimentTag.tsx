import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import type { SentimentLabel } from '../sentimentUtils'

export interface SentimentScores {
    positive: number
    neutral: number
    negative: number
}

interface SentimentTagProps {
    label: string
    score: number
    scores?: SentimentScores
    loading?: boolean
}

const SENTIMENT_TAG_TYPE: Record<SentimentLabel, LemonTagProps['type']> = {
    positive: 'success',
    negative: 'danger',
    neutral: 'none',
}

export const SENTIMENT_BAR_COLOR: Record<SentimentLabel, string> = {
    positive: 'bg-success',
    negative: 'bg-danger',
    neutral: 'bg-border',
}

function formatScore(score: number | undefined): string {
    if (score === undefined || score === null) {
        return '?'
    }
    return `${Math.round(score * 100)}%`
}

function buildTooltip(label: string, scores?: SentimentScores): string {
    if (!scores) {
        return `Sentiment: ${label}`
    }
    return `Positive: ${formatScore(scores.positive)}\nNeutral: ${formatScore(scores.neutral)}\nNegative: ${formatScore(scores.negative)}`
}

export function SentimentTag({ label, score, scores, loading }: SentimentTagProps): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="h-5 w-20" />
    }

    const tagType = SENTIMENT_TAG_TYPE[label as SentimentLabel] ?? 'none'

    return (
        <Tooltip title={<span className="whitespace-pre-line">{buildTooltip(label, scores)}</span>}>
            <LemonTag type={tagType} size="small" className="cursor-default capitalize">
                Sentiment: {label} ({formatScore(score)})
            </LemonTag>
        </Tooltip>
    )
}

export interface MessageSentiment {
    label: string
    score: number
}

interface MessageScore {
    label?: string
    scores?: Record<string, number>
}

export interface SentimentBarProps {
    label: string
    score: number
    loading?: boolean
    // Individual message scores for computing max positive/negative tick marks.
    // Pass generation messages directly, or flatten from multiple generations.
    messages?: Record<string | number, MessageScore>
}

function computeExtremes(messages?: Record<string | number, MessageScore>): {
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

export function SentimentBar({ label, score, loading, messages }: SentimentBarProps): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-1.5 w-10" />
    }

    const sentimentLabel = (label as SentimentLabel) ?? 'neutral'
    const barColor = SENTIMENT_BAR_COLOR[sentimentLabel] ?? 'bg-border'
    const widthPercent = Math.round(score * 100)
    const { maxPositive, maxNegative } = computeExtremes(messages)
    const showMaxPositive = maxPositive > 0.05
    const showMaxNegative = maxNegative > 0.05

    const capitalize = (s: string): string => s[0].toUpperCase() + s.slice(1)
    const tooltipParts = [`${capitalize(sentimentLabel)}: ${widthPercent}%`]
    if (showMaxPositive) {
        tooltipParts.push(`max positive: ${Math.round(maxPositive * 100)}%`)
    }
    if (showMaxNegative) {
        tooltipParts.push(`max negative: ${Math.round(maxNegative * 100)}%`)
    }
    const tooltipText =
        tooltipParts.length > 1 ? `${tooltipParts[0]} (${tooltipParts.slice(1).join(', ')})` : tooltipParts[0]

    return (
        <Tooltip title={tooltipText}>
            <span className="relative w-10 my-0.5 inline-block shrink-0">
                <span className="block h-1.5 bg-border-light rounded-full overflow-hidden">
                    <span
                        className={`block h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </span>
                {showMaxPositive && (
                    <span
                        className="absolute w-0.5 bg-success rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: `${Math.round(maxPositive * 100)}%`, top: '-2px', bottom: 0 }}
                    />
                )}
                {showMaxNegative && (
                    <span
                        className="absolute w-0.5 bg-danger rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: `${Math.round(maxNegative * 100)}%`, top: 0, bottom: '-2px' }}
                    />
                )}
            </span>
        </Tooltip>
    )
}

/** Flatten all messages from all generations into a single record for SentimentBar. */
export function flattenGenerationMessages(
    generations?: Record<string, { messages?: Record<string | number, MessageScore> }>
): Record<string, MessageScore> | undefined {
    if (!generations) {
        return undefined
    }
    const flat: Record<string, MessageScore> = {}
    for (const [genId, gen] of Object.entries(generations)) {
        for (const [msgId, msg] of Object.entries(gen.messages ?? {})) {
            flat[`${genId}:${msgId}`] = msg
        }
    }
    return Object.keys(flat).length > 0 ? flat : undefined
}

export function MessageSentimentBar({ sentiment }: { sentiment: MessageSentiment }): JSX.Element | null {
    const sentimentLabel = sentiment.label as SentimentLabel
    if (!SENTIMENT_BAR_COLOR[sentimentLabel]) {
        return null
    }
    const widthPercent = Math.round(sentiment.score * 100)
    const barColor = SENTIMENT_BAR_COLOR[sentimentLabel]

    return (
        <Tooltip
            title={`${sentiment.label[0].toUpperCase()}${sentiment.label.slice(1)}: ${formatScore(sentiment.score)}`}
        >
            <span className="flex items-center gap-1">
                <span className="w-10 h-1.5 bg-border-light rounded-full overflow-hidden inline-block">
                    <span
                        className={`block h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </span>
            </span>
        </Tooltip>
    )
}
