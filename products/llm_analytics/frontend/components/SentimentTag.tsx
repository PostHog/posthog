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

export function SentimentBar({ label, score, scores, loading }: SentimentTagProps): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-1.5 w-10" />
    }

    const sentimentLabel = (label as SentimentLabel) ?? 'neutral'
    const barColor = SENTIMENT_BAR_COLOR[sentimentLabel] ?? 'bg-border'
    const widthPercent = Math.round(score * 100)

    return (
        <Tooltip title={<span className="whitespace-pre-line">{buildTooltip(label, scores)}</span>}>
            <div className="relative w-10 my-0.5 shrink-0">
                <div className="h-1.5 bg-border-light rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full ${barColor}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${widthPercent}%` }}
                    />
                </div>
            </div>
        </Tooltip>
    )
}

export interface MessageSentiment {
    label: string
    score: number
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
