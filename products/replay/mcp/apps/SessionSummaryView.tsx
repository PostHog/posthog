import { type ReactElement } from 'react'

import { Badge, Card, Stack } from '@posthog/mosaic'

export interface SessionSummarySegment {
    index?: number | null
    name?: string | null
    meta?: {
        duration?: number | null
        duration_percentage?: number | null
        events_count?: number | null
        events_percentage?: number | null
        key_action_count?: number | null
        failure_count?: number | null
        abandonment_count?: number | null
        confusion_count?: number | null
        exception_count?: number | null
    } | null
}

export interface SessionSummarySegmentOutcome {
    segment_index?: number | null
    summary?: string | null
    success?: boolean | null
}

export interface SessionSummaryOutcome {
    description?: string | null
    success?: boolean | null
}

export interface SessionSummarySentiment {
    frustration_score?: number | null
    outcome?: string | null
    sentiment_signals?: Array<{
        signal_type?: string | null
        segment_index?: number | null
        description?: string | null
        intensity?: number | null
    }> | null
}

export interface SessionSummaryData {
    [sessionId: string]: {
        segments?: SessionSummarySegment[] | null
        segment_outcomes?: SessionSummarySegmentOutcome[] | null
        session_outcome?: SessionSummaryOutcome | null
        sentiment?: SessionSummarySentiment | null
        key_actions?: Array<{
            segment_index?: number | null
            events?: Array<{
                description?: string | null
                abandonment?: boolean | null
                confusion?: boolean | null
                exception?: string | null
            }> | null
        }> | null
    }
}

function formatDuration(seconds?: number | null): string {
    if (seconds == null) {
        return '\u2014'
    }
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = seconds % 60
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatPercentage(value?: number | null): string {
    if (value == null) {
        return ''
    }
    return `(${(value * 100).toFixed(2)}%)`
}

function issueCount(segment: SessionSummarySegment): number {
    const meta = segment.meta
    if (!meta) {
        return 0
    }
    return (
        (meta.failure_count ?? 0) +
        (meta.abandonment_count ?? 0) +
        (meta.confusion_count ?? 0) +
        (meta.exception_count ?? 0)
    )
}

export function SessionSummaryView({ data }: { data: SessionSummaryData }): ReactElement {
    const sessionIds = Object.keys(data)
    if (sessionIds.length === 0) {
        return <div className="p-4 text-sm text-text-secondary">No summary data available.</div>
    }

    return (
        <div className="p-4">
            <Stack gap="lg">
                {sessionIds.map((sessionId) => {
                    const summary = data[sessionId]
                    if (!summary) {
                        return null
                    }
                    return <SingleSessionSummary key={sessionId} sessionId={sessionId} summary={summary} />
                })}
            </Stack>
        </div>
    )
}

function SingleSessionSummary({
    sessionId,
    summary,
}: {
    sessionId: string
    summary: NonNullable<SessionSummaryData[string]>
}): ReactElement {
    const outcome = summary.session_outcome
    const segments = summary.segments ?? []
    const segmentOutcomes = summary.segment_outcomes ?? []
    const keyActions = summary.key_actions ?? []

    const outcomesByIndex = new Map(segmentOutcomes.map((o) => [o.segment_index, o]))
    const keyActionsByIndex = new Map(keyActions.map((ka) => [ka.segment_index, ka]))

    return (
        <Stack gap="md">
            <span className="text-xs font-mono text-text-secondary">{sessionId}</span>

            {outcome && (
                <div
                    className="rounded-lg p-3"
                    style={{
                        backgroundColor: outcome.success
                            ? 'var(--color-bg-success, #f0fdf4)'
                            : 'var(--color-bg-danger, #fef2f2)',
                        borderLeft: `4px solid ${outcome.success ? 'var(--color-success, #22c55e)' : 'var(--color-danger, #ef4444)'}`,
                    }}
                >
                    <div className="flex items-start gap-2">
                        <span className="text-lg">{outcome.success ? '\u2713' : '\u26A0'}</span>
                        <div>
                            <span className="text-sm font-semibold text-text-primary">Session outcome: </span>
                            <span className="text-sm text-text-primary">{outcome.description ?? '\u2014'}</span>
                        </div>
                    </div>
                </div>
            )}

            {segments.map((segment) => {
                const segOutcome = outcomesByIndex.get(segment.index ?? -1)
                const segActions = keyActionsByIndex.get(segment.index ?? -1)
                const issues = issueCount(segment)

                return (
                    <Card key={segment.index} padding="md">
                        <div
                            style={{
                                borderLeft: `3px solid ${segOutcome?.success === false ? 'var(--color-danger, #ef4444)' : segOutcome?.success === true ? 'var(--color-success, #22c55e)' : 'var(--color-border-primary, #e5e7eb)'}`,
                                paddingLeft: '12px',
                            }}
                        >
                            <Stack gap="sm">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm font-semibold text-text-primary">
                                        {segment.name ?? `Segment ${segment.index}`}
                                    </span>
                                    {segOutcome?.success !== undefined && segOutcome?.success !== null && (
                                        <Badge variant={segOutcome.success ? 'success' : 'danger'} size="sm">
                                            {segOutcome.success ? 'success' : 'failed'}
                                        </Badge>
                                    )}
                                </div>

                                {segOutcome?.summary && (
                                    <span className="text-sm text-text-secondary">{segOutcome.summary}</span>
                                )}

                                <div className="flex gap-6 flex-wrap text-xs text-text-secondary">
                                    <span>Key actions: {segment.meta?.key_action_count ?? 0}</span>
                                    {issues > 0 && <span className="text-danger">Issues: {issues}</span>}
                                </div>

                                <div className="flex gap-6 flex-wrap text-xs text-text-secondary">
                                    <span>
                                        Duration: {formatDuration(segment.meta?.duration)}{' '}
                                        {formatPercentage(segment.meta?.duration_percentage)}
                                    </span>
                                    <span>
                                        Events: {segment.meta?.events_count ?? 0}{' '}
                                        {formatPercentage(segment.meta?.events_percentage)}
                                    </span>
                                </div>

                                {segActions?.events && segActions.events.length > 0 && (
                                    <div className="mt-1">
                                        <details>
                                            <summary className="text-xs text-text-secondary cursor-pointer">
                                                Key actions ({segActions.events.length})
                                            </summary>
                                            <ul className="mt-1 ml-4 list-disc">
                                                {segActions.events.map((event, i) => (
                                                    <li key={i} className="text-xs text-text-primary mt-1">
                                                        {event.description}
                                                        {event.exception && (
                                                            <Badge variant="danger" size="sm" className="ml-1">
                                                                {event.exception}
                                                            </Badge>
                                                        )}
                                                        {event.abandonment && (
                                                            <Badge variant="warning" size="sm" className="ml-1">
                                                                abandonment
                                                            </Badge>
                                                        )}
                                                        {event.confusion && (
                                                            <Badge variant="warning" size="sm" className="ml-1">
                                                                confusion
                                                            </Badge>
                                                        )}
                                                    </li>
                                                ))}
                                            </ul>
                                        </details>
                                    </div>
                                )}
                            </Stack>
                        </div>
                    </Card>
                )
            })}

            {summary.sentiment && <SentimentSection sentiment={summary.sentiment} />}
        </Stack>
    )
}

function SentimentSection({ sentiment }: { sentiment: SessionSummarySentiment }): ReactElement {
    const outcomeColors: Record<string, string> = {
        successful: 'var(--color-success, #22c55e)',
        friction: 'var(--color-warning, #f59e0b)',
        frustrated: 'var(--color-danger, #ef4444)',
        blocked: 'var(--color-danger, #ef4444)',
    }

    const color = outcomeColors[sentiment.outcome ?? ''] ?? 'var(--color-text-secondary)'

    return (
        <Card padding="md">
            <Stack gap="sm">
                <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-text-primary">Sentiment</span>
                    {sentiment.outcome && (
                        <Badge
                            variant={
                                sentiment.outcome === 'successful'
                                    ? 'success'
                                    : sentiment.outcome === 'friction'
                                      ? 'warning'
                                      : 'danger'
                            }
                            size="sm"
                        >
                            {sentiment.outcome}
                        </Badge>
                    )}
                </div>
                {sentiment.frustration_score != null && (
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-text-secondary">Frustration:</span>
                        <div
                            className="h-2 rounded-full"
                            style={{
                                width: '100px',
                                backgroundColor: 'var(--color-bg-tertiary, #f2f4f7)',
                            }}
                        >
                            <div
                                className="h-2 rounded-full"
                                style={{
                                    width: `${Math.round(sentiment.frustration_score * 100)}%`,
                                    backgroundColor: color,
                                }}
                            />
                        </div>
                        <span className="text-xs text-text-secondary">
                            {Math.round(sentiment.frustration_score * 100)}%
                        </span>
                    </div>
                )}
            </Stack>
        </Card>
    )
}
