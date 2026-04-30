import { type ReactElement, useState } from 'react'

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

interface KeyActionEvent {
    description?: string | null
    abandonment?: boolean | null
    confusion?: boolean | null
    exception?: string | null
    milliseconds_since_start?: number | null
    current_url?: string | null
}

interface SessionSummaryEntry {
    segments?: SessionSummarySegment[] | null
    segment_outcomes?: SessionSummarySegmentOutcome[] | null
    session_outcome?: SessionSummaryOutcome | null
    sentiment?: SessionSummarySentiment | null
    key_actions?: Array<{
        segment_index?: number | null
        events?: KeyActionEvent[] | null
    }> | null
}

interface RecordingMetadata {
    id?: string
    recording_duration?: number | null
    active_seconds?: number | null
    inactive_seconds?: number | null
    click_count?: number | null
    keypress_count?: number | null
    mouse_activity_count?: number | null
    console_error_count?: number | null
    console_warn_count?: number | null
    console_log_count?: number | null
    activity_score?: number | null
    start_time?: string | null
    end_time?: string | null
}

export interface SessionSummaryData {
    summaries?: Record<string, SessionSummaryEntry> | null
    recordings?: Record<string, RecordingMetadata> | null
    // Legacy format: direct session ID → summary mapping
    [key: string]: unknown
}

function parseSummaryData(data: SessionSummaryData): {
    summaries: Record<string, SessionSummaryEntry>
    recordings: Record<string, RecordingMetadata>
} {
    if (data.summaries && typeof data.summaries === 'object') {
        return {
            summaries: data.summaries as Record<string, SessionSummaryEntry>,
            recordings: (data.recordings as Record<string, RecordingMetadata>) ?? {},
        }
    }
    // Legacy format: top-level keys are session IDs
    const summaries: Record<string, SessionSummaryEntry> = {}
    for (const [key, value] of Object.entries(data)) {
        if (key.startsWith('_') || key === 'summaries' || key === 'recordings') {
            continue
        }
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            summaries[key] = value as SessionSummaryEntry
        }
    }
    return { summaries, recordings: {} }
}

function formatDuration(seconds?: number | null): string {
    if (seconds == null) {
        return '\u2014'
    }
    const m = Math.floor(seconds / 60)
    const s = Math.round(seconds % 60)
    return `${m}m ${s}s`
}

function formatTimestamp(ms?: number | null): string {
    if (ms == null) {
        return ''
    }
    const totalSeconds = Math.floor(ms / 1000)
    const h = Math.floor(totalSeconds / 3600)
    const m = Math.floor((totalSeconds % 3600) / 60)
    const s = totalSeconds % 60
    if (h > 0) {
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatPercentage(value?: number | null): string {
    if (value == null) {
        return ''
    }
    return `${(value * 100).toFixed(1)}%`
}

function SegmentTimelineBar({
    offsetPercent,
    widthPercent,
    success,
}: {
    offsetPercent: number
    widthPercent: number
    success?: boolean | null
}): ReactElement {
    const barColor =
        success === false
            ? 'var(--color-danger, #ef4444)'
            : success === true
              ? 'var(--color-success, #22c55e)'
              : 'var(--color-border-primary, #94a3b8)'

    return (
        <div className="w-full h-2 rounded-full" style={{ backgroundColor: 'var(--color-bg-tertiary, #f2f4f7)' }}>
            <div
                className="h-2 rounded-full"
                style={{
                    marginLeft: `${offsetPercent}%`,
                    width: `${Math.max(widthPercent, 1)}%`,
                    backgroundColor: barColor,
                }}
            />
        </div>
    )
}

function ChevronIcon({ expanded }: { expanded: boolean }): ReactElement {
    return (
        <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            style={{
                transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
                transition: 'transform 0.15s ease',
                flexShrink: 0,
            }}
        >
            <path
                d="M6 4l4 4-4 4"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    )
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }): ReactElement {
    return (
        <div
            className="rounded-lg p-3 flex-1"
            style={{ backgroundColor: 'var(--color-bg-secondary, #f5f5f5)', minWidth: '100px' }}
        >
            <div className="text-xs text-text-secondary">{label}</div>
            <div className="text-lg font-semibold text-text-primary">{value}</div>
            {sub && <div className="text-xs text-text-secondary">{sub}</div>}
        </div>
    )
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
    const { summaries, recordings } = parseSummaryData(data)
    const sessionIds = Object.keys(summaries)

    if (sessionIds.length === 0) {
        return <div className="p-4 text-sm text-text-secondary">No summary data available.</div>
    }

    return (
        <div className="p-4">
            <Stack gap="lg">
                {sessionIds.map((sessionId) => {
                    const summary = summaries[sessionId]
                    if (!summary) {
                        return null
                    }
                    return (
                        <SingleSessionSummary
                            key={sessionId}
                            sessionId={sessionId}
                            summary={summary}
                            recording={recordings[sessionId]}
                        />
                    )
                })}
            </Stack>
        </div>
    )
}

function RecordingStatsHeader({ recording }: { recording: RecordingMetadata }): ReactElement {
    const duration = recording.recording_duration
    const activeSeconds = recording.active_seconds

    return (
        <div className="flex gap-2 flex-wrap">
            <StatCard
                label="Duration"
                value={formatDuration(duration)}
                sub={activeSeconds != null ? `${formatDuration(activeSeconds)} active` : undefined}
            />
            <StatCard
                label="Console errors"
                value={String(recording.console_error_count ?? 0)}
                sub={recording.console_warn_count ? `${recording.console_warn_count} warnings` : undefined}
            />
            <StatCard
                label="Clicks"
                value={String(recording.click_count ?? 0)}
                sub={recording.mouse_activity_count ? `${recording.mouse_activity_count} mouse events` : undefined}
            />
            <StatCard
                label="Keypresses"
                value={String(recording.keypress_count ?? 0)}
                sub={recording.activity_score != null ? `activity ${recording.activity_score.toFixed(1)}` : undefined}
            />
        </div>
    )
}

function SingleSessionSummary({
    sessionId,
    summary,
    recording,
}: {
    sessionId: string
    summary: SessionSummaryEntry
    recording?: RecordingMetadata
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
                            <span className="text-sm font-semibold text-text-primary">
                                {outcome.success ? 'Session successful' : 'Session abandoned'}
                            </span>
                            <div className="text-sm text-text-primary mt-1">{outcome.description ?? '\u2014'}</div>
                        </div>
                    </div>
                </div>
            )}

            {recording && <RecordingStatsHeader recording={recording} />}

            <span className="text-sm font-semibold text-text-primary">Journey</span>

            {segments.map((segment, i) => {
                const segOutcome = outcomesByIndex.get(segment.index ?? -1)
                const segActions = keyActionsByIndex.get(segment.index ?? -1)

                const offsetPercent =
                    segments.slice(0, i).reduce((sum, s) => sum + (s.meta?.duration_percentage ?? 0), 0) * 100
                const widthPercent = (segment.meta?.duration_percentage ?? 0) * 100

                return (
                    <SegmentCard
                        key={segment.index}
                        segment={segment}
                        segOutcome={segOutcome}
                        segActions={segActions}
                        offsetPercent={offsetPercent}
                        widthPercent={widthPercent}
                    />
                )
            })}

            {summary.sentiment && <SentimentSection sentiment={summary.sentiment} />}
        </Stack>
    )
}

function SegmentCard({
    segment,
    segOutcome,
    segActions,
    offsetPercent,
    widthPercent,
}: {
    segment: SessionSummarySegment
    segOutcome?: SessionSummarySegmentOutcome
    segActions?: { segment_index?: number | null; events?: KeyActionEvent[] | null }
    offsetPercent: number
    widthPercent: number
}): ReactElement {
    const [expanded, setExpanded] = useState(false)
    const issues = issueCount(segment)
    const hasEvents = segActions?.events && segActions.events.length > 0

    const borderColor =
        segOutcome?.success === false
            ? 'var(--color-danger, #ef4444)'
            : segOutcome?.success === true
              ? 'var(--color-success, #22c55e)'
              : 'var(--color-border-primary, #e5e7eb)'

    return (
        <Card padding="none" className="overflow-hidden">
            <div
                onClick={hasEvents ? () => setExpanded(!expanded) : undefined}
                style={{
                    borderLeft: `3px solid ${borderColor}`,
                    cursor: hasEvents ? 'pointer' : 'default',
                    padding: '12px',
                    paddingLeft: '15px',
                }}
            >
                <Stack gap="sm">
                    <div className="flex items-center gap-2">
                        {hasEvents && (
                            <span className="text-text-secondary">
                                <ChevronIcon expanded={expanded} />
                            </span>
                        )}
                        <span className="text-sm font-semibold text-text-primary flex-1">
                            {segment.name ?? `Segment ${segment.index}`}
                        </span>
                        {issues > 0 && (
                            <Badge variant="danger" size="sm">
                                {issues} {issues === 1 ? 'issue' : 'issues'}
                            </Badge>
                        )}
                        {segOutcome?.success !== undefined && segOutcome?.success !== null && (
                            <Badge variant={segOutcome.success ? 'success' : 'danger'} size="sm">
                                {segOutcome.success ? 'success' : 'failed'}
                            </Badge>
                        )}
                    </div>

                    {segOutcome?.summary && <span className="text-sm text-text-secondary">{segOutcome.summary}</span>}

                    <div className="flex items-center gap-3">
                        <div className="flex-1">
                            <SegmentTimelineBar
                                offsetPercent={offsetPercent}
                                widthPercent={widthPercent}
                                success={segOutcome?.success}
                            />
                        </div>
                        <span className="text-xs text-text-secondary whitespace-nowrap">
                            {formatDuration(segment.meta?.duration)} &middot;{' '}
                            {formatPercentage(segment.meta?.duration_percentage)}
                        </span>
                    </div>
                </Stack>
            </div>

            {expanded && hasEvents && (
                <div
                    style={{
                        borderLeft: `3px solid ${borderColor}`,
                        borderTop: '1px solid var(--color-border-primary, #e5e7eb)',
                        padding: '8px 12px 12px 15px',
                    }}
                >
                    <div className="flex flex-col gap-0">
                        {segActions.events!.map((event, i) => (
                            <div
                                key={i}
                                style={{
                                    borderBottom:
                                        i < segActions.events!.length - 1
                                            ? '1px solid var(--color-border-primary, #e5e7eb)'
                                            : 'none',
                                    padding: '8px 0',
                                }}
                            >
                                <div className="flex items-start gap-3">
                                    {event.milliseconds_since_start != null && (
                                        <span
                                            className="text-xs font-mono whitespace-nowrap"
                                            style={{ color: 'var(--color-warning, #f59e0b)' }}
                                        >
                                            {formatTimestamp(event.milliseconds_since_start)}
                                        </span>
                                    )}
                                    <div className="flex-1">
                                        <div className="flex items-center gap-1 flex-wrap">
                                            <span className="text-xs text-text-primary">{event.description}</span>
                                            {event.exception && (
                                                <Badge variant="danger" size="sm">
                                                    {event.exception}
                                                </Badge>
                                            )}
                                            {event.abandonment && (
                                                <Badge variant="warning" size="sm">
                                                    abandonment
                                                </Badge>
                                            )}
                                            {event.confusion && (
                                                <Badge variant="warning" size="sm">
                                                    confusion
                                                </Badge>
                                            )}
                                        </div>
                                        {event.current_url && (
                                            <span className="text-xs text-text-secondary">{event.current_url}</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </Card>
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
