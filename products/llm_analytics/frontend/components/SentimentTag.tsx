import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { SENTIMENT_COLOR, SentimentLabel, SentimentScores, getSentimentLabelFromScores } from '../sentimentUtils'

export type { SentimentLabel }
export { SENTIMENT_COLOR }

const SENTIMENT_TAG_TYPE: Record<SentimentLabel, LemonTagProps['type']> = {
    positive: 'success',
    negative: 'danger',
    neutral: 'none',
}

function getSentimentLabel(event: LLMTraceEvent): SentimentLabel | null {
    const label = event.properties.$ai_sentiment_label
    if (label === 'positive' || label === 'neutral' || label === 'negative') {
        return label
    }
    return null
}

function formatScore(score: number | undefined): string {
    if (score === undefined || score === null) {
        return '?'
    }
    return `${Math.round(score * 100)}%`
}

function buildSentimentTooltip(
    label: SentimentLabel,
    score: number,
    maxPositive?: number,
    maxNegative?: number
): string {
    let text = `${label[0].toUpperCase()}${label.slice(1)}: ${formatScore(score)}`
    if (maxPositive !== undefined || maxNegative !== undefined) {
        text += ` (max positive: ${formatScore(maxPositive)}, max negative: ${formatScore(maxNegative)})`
    }
    return text
}

export function SentimentTag({ event }: { event: LLMTraceEvent }): JSX.Element | null {
    const label = getSentimentLabel(event)
    if (!label) {
        return null
    }
    const scores = event.properties.$ai_sentiment_scores
    const score = scores ? Math.max(scores.positive ?? 0, scores.neutral ?? 0, scores.negative ?? 0) : undefined
    const tagType = SENTIMENT_TAG_TYPE[label]

    return (
        <Tooltip
            title={buildSentimentTooltip(
                label,
                score ?? 0,
                event.properties.$ai_sentiment_positive_max_score,
                event.properties.$ai_sentiment_negative_max_score
            )}
        >
            <LemonTag type={tagType} size="small">
                Sentiment: {label}
                {score !== undefined ? ` (${formatScore(score)})` : ''}
            </LemonTag>
        </Tooltip>
    )
}

export function SentimentDot({ event }: { event: LLMTraceEvent }): JSX.Element | null {
    const label = getSentimentLabel(event)
    if (!label) {
        return null
    }

    const scores = event.properties.$ai_sentiment_scores
    if (!scores) {
        const dotColor = SENTIMENT_COLOR[label]
        return (
            <Tooltip title={`${label[0].toUpperCase()}${label.slice(1)}`}>
                <span className={`inline-block w-2 h-2 rounded-full ${dotColor} shrink-0`} />
            </Tooltip>
        )
    }

    const positive = scores.positive ?? 0
    const neutral = scores.neutral ?? 0
    const negative = scores.negative ?? 0
    const derivedLabel = getSentimentLabelFromScores(positive, neutral, negative)
    const maxScore = Math.max(positive, neutral, negative)
    const barColor = SENTIMENT_COLOR[derivedLabel]
    const widthPercent = Math.round(maxScore * 100)

    const maxPositive: number | undefined = event.properties.$ai_sentiment_positive_max_score
    const maxNegative: number | undefined = event.properties.$ai_sentiment_negative_max_score
    const showMaxPositive = maxPositive !== undefined && maxPositive > 0 && Math.abs(maxPositive - positive) > 0.05
    const showMaxNegative = maxNegative !== undefined && maxNegative > 0 && Math.abs(maxNegative - negative) > 0.05

    return (
        <Tooltip title={buildSentimentTooltip(derivedLabel, maxScore, maxPositive, maxNegative)}>
            <div className="relative w-10 my-0.5 shrink-0">
                <div className="h-1.5 bg-border-light rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </div>
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
            </div>
        </Tooltip>
    )
}

export function UserSentimentBar({ scores }: { scores: SentimentScores }): JSX.Element | null {
    const [positive, neutral, negative, count] = scores
    const maxPositive = scores.length > 4 ? scores[4] : undefined
    const maxNegative = scores.length > 5 ? scores[5] : undefined

    if (!count || count === 0) {
        return <>–</>
    }

    const label = getSentimentLabelFromScores(positive, neutral, negative)
    const maxScore = Math.max(positive, neutral, negative)
    const barColor = SENTIMENT_COLOR[label]
    const widthPercent = Math.round(maxScore * 100)

    const showMaxPositive = maxPositive !== undefined && maxPositive > 0 && Math.abs(maxPositive - positive) > 0.05
    const showMaxNegative = maxNegative !== undefined && maxNegative > 0 && Math.abs(maxNegative - negative) > 0.05

    return (
        <Tooltip title={buildSentimentTooltip(label, maxScore, maxPositive, maxNegative)}>
            <div className="relative w-16 my-0.5">
                <div className="h-1.5 bg-border-light rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </div>
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
            </div>
        </Tooltip>
    )
}

export interface MessageSentiment {
    label: string
    score: number
}

export function MessageSentimentBar({ sentiment }: { sentiment: MessageSentiment }): JSX.Element | null {
    const label = sentiment.label as SentimentLabel
    if (!SENTIMENT_COLOR[label]) {
        return null
    }
    const widthPercent = typeof sentiment.score === 'number' ? Math.round(sentiment.score * 100) : 50
    const barColor = SENTIMENT_COLOR[label]
    const tooltipText = `${label[0].toUpperCase()}${label.slice(1)}: ${formatScore(sentiment.score)}`

    return (
        <Tooltip title={tooltipText}>
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
