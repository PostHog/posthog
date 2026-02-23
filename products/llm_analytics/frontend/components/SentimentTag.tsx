import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import type { MessageSentiment } from '../llmSentimentLazyLoaderLogic'
import type { SentimentLabel } from '../sentimentUtils'
import { buildSentimentBarTooltip, buildTagTooltip, capitalize, computeExtremes, formatScore } from '../sentimentUtils'

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

export function SentimentTag({ label, score, scores, loading }: SentimentTagProps): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="h-5 w-20" />
    }

    const tagType = SENTIMENT_TAG_TYPE[label as SentimentLabel] ?? 'none'

    return (
        <Tooltip title={<span className="whitespace-pre-line">{buildTagTooltip(label, scores)}</span>}>
            <LemonTag type={tagType} size="small" className="cursor-default capitalize">
                Sentiment: {label} ({formatScore(score)})
            </LemonTag>
        </Tooltip>
    )
}

interface MessageScore {
    label?: string
    scores?: Record<string, number>
}

export interface SentimentBarProps {
    label: string
    score: number
    loading?: boolean
    /** "sm" (default) for inline contexts, "full" to fill available width. */
    size?: 'sm' | 'full'
    // Individual message scores for computing max positive/negative tick marks.
    // Pass generation messages directly, or flatten from multiple generations.
    messages?: Record<string | number, MessageScore>
}

export function SentimentBar({ label, score, loading, size = 'sm', messages }: SentimentBarProps): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className={`h-1.5 ${size === 'full' ? 'w-3/4' : 'w-10'}`} />
    }

    const sentimentLabel = (label as SentimentLabel) || 'neutral'
    const barColor = SENTIMENT_BAR_COLOR[sentimentLabel] ?? 'bg-border'
    const widthPercent = Math.round(score * 100)
    const { maxPositive, maxNegative } = computeExtremes(messages)
    const showMaxPositive = maxPositive > 0.05
    const showMaxNegative = maxNegative > 0.05
    const tooltipText = buildSentimentBarTooltip(sentimentLabel, widthPercent, maxPositive, maxNegative)

    return (
        <Tooltip title={tooltipText}>
            <span className={`relative my-0.5 inline-block shrink-0 ${size === 'full' ? 'w-3/4' : 'w-10'}`}>
                <span className="block h-1.5 bg-border-light rounded-full overflow-hidden">
                    <span
                        className={`block h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </span>
                {showMaxPositive && (
                    <span
                        className="absolute"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `${Math.round(maxPositive * 100)}%`,
                            top: '-5px',
                            marginLeft: '-3px',
                            width: 0,
                            height: 0,
                            borderLeft: '3px solid transparent',
                            borderRight: '3px solid transparent',
                            borderTop: '4px solid var(--success)',
                        }}
                    />
                )}
                {showMaxNegative && (
                    <span
                        className="absolute"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `${Math.round(maxNegative * 100)}%`,
                            bottom: '-5px',
                            marginLeft: '-3px',
                            width: 0,
                            height: 0,
                            borderLeft: '3px solid transparent',
                            borderRight: '3px solid transparent',
                            borderBottom: '4px solid var(--danger)',
                        }}
                    />
                )}
            </span>
        </Tooltip>
    )
}

export function MessageSentimentBar({ sentiment }: { sentiment: MessageSentiment }): JSX.Element | null {
    const sentimentLabel = sentiment.label as SentimentLabel
    if (!SENTIMENT_BAR_COLOR[sentimentLabel]) {
        return null
    }
    const widthPercent = Math.round(sentiment.score * 100)
    const barColor = SENTIMENT_BAR_COLOR[sentimentLabel]

    return (
        <Tooltip title={`${capitalize(sentimentLabel)}: ${formatScore(sentiment.score)}`}>
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
