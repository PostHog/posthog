import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

type SentimentLabel = 'positive' | 'neutral' | 'negative'

const SENTIMENT_TAG_TYPE: Record<SentimentLabel, LemonTagProps['type']> = {
    positive: 'success',
    negative: 'danger',
    neutral: 'muted',
}

const SENTIMENT_DOT_COLOR: Record<SentimentLabel, string> = {
    positive: 'bg-success',
    negative: 'bg-danger',
    neutral: 'bg-muted-alt',
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

function buildTooltip(event: LLMTraceEvent): string {
    const scores = event.properties.$ai_sentiment_scores
    if (!scores) {
        return `Sentiment: ${event.properties.$ai_sentiment_label ?? 'unknown'}`
    }
    return `Positive: ${formatScore(scores.positive)} / Neutral: ${formatScore(scores.neutral)} / Negative: ${formatScore(scores.negative)}`
}

export function SentimentTag({ event }: { event: LLMTraceEvent }): JSX.Element | null {
    const label = getSentimentLabel(event)
    if (!label) {
        return null
    }
    const score = event.properties.$ai_sentiment_score
    const tagType = SENTIMENT_TAG_TYPE[label]

    return (
        <Tooltip title={buildTooltip(event)}>
            <LemonTag type={tagType} size="small">
                Sentiment: {label}
                {score !== undefined && score !== null ? ` (${formatScore(score)})` : ''}
            </LemonTag>
        </Tooltip>
    )
}

export function SentimentDot({ event }: { event: LLMTraceEvent }): JSX.Element | null {
    const label = getSentimentLabel(event)
    if (!label) {
        return null
    }
    const dotColor = SENTIMENT_DOT_COLOR[label]

    return (
        <Tooltip title={buildTooltip(event)}>
            <span className={`inline-block w-2 h-2 rounded-full ${dotColor} shrink-0`} />
        </Tooltip>
    )
}

const SENTIMENT_BAR_COLOR: Record<SentimentLabel, string> = {
    positive: 'bg-success',
    negative: 'bg-danger',
    neutral: 'bg-muted-alt',
}

export function SentimentBar({ event }: { event: LLMTraceEvent }): JSX.Element | null {
    const label = getSentimentLabel(event)
    if (!label) {
        return null
    }
    const score = event.properties.$ai_sentiment_score
    const widthPercent = typeof score === 'number' ? Math.round(score * 100) : 50
    const barColor = SENTIMENT_BAR_COLOR[label]

    return (
        <Tooltip title={buildTooltip(event)}>
            <div className="w-16 h-1.5 bg-border-light rounded-full overflow-hidden">
                <div
                    className={`h-full rounded-full ${barColor}`}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${widthPercent}%` }}
                />
            </div>
        </Tooltip>
    )
}
