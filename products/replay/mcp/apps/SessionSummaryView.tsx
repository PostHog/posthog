import { AlertTriangle, Check, ChevronRight } from 'lucide-react'
import { type ReactElement, useState } from 'react'

import { Badge, Card, CardContent, cn, Progress } from '@posthog/quill'

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

export interface SessionSummaryData {
    [key: string]: unknown
}

function parseSummaries(data: SessionSummaryData): Record<string, SessionSummaryEntry> {
    const summaries: Record<string, SessionSummaryEntry> = {}
    for (const [key, value] of Object.entries(data)) {
        if (key.startsWith('_')) {
            continue
        }
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            summaries[key] = value as SessionSummaryEntry
        }
    }
    return summaries
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

// Bespoke (intentionally — not @posthog/quill `Progress`).
//
// `Progress` models a single 0-100% fill anchored to the start of the track.
// This bar is a *segment* on a timeline: it has an `offsetPercent` (where
// in the session the segment starts) AND a `widthPercent` (how much of the
// session it covers). Base UI's Progress.Root has no concept of an offset;
// you'd have to absolute-position the indicator with custom CSS, defeating
// the purpose of using the primitive.
//
// If Quill ever ships a `Timeline` / `RangeIndicator` primitive that
// supports start+end (or offset+length), migrate to that. Until then this
// stays a small custom div + token-aligned colours.
function SegmentTimelineBar({
    offsetPercent,
    widthPercent,
    success,
}: {
    offsetPercent: number
    widthPercent: number
    success?: boolean | null | undefined
}): ReactElement {
    const fillClass = success === false ? 'bg-destructive' : success === true ? 'bg-success' : 'bg-muted-foreground'

    return (
        <div className="w-full h-2 rounded-full bg-muted">
            <div
                className={cn('h-2 rounded-full', fillClass)}
                style={{
                    marginLeft: `${offsetPercent}%`,
                    width: `${Math.max(widthPercent, 1)}%`,
                }}
            />
        </div>
    )
}

function issueCount(segment: SessionSummarySegment): number {
    return segment.meta?.failure_count ?? 0
}

export function SessionSummaryView({ data }: { data: SessionSummaryData }): ReactElement {
    const summaries = parseSummaries(data)
    const sessionIds = Object.keys(summaries)

    if (sessionIds.length === 0) {
        return <div className="p-4 text-sm text-muted-foreground">No summary data available.</div>
    }

    return (
        <div className="p-4">
            <div className="flex flex-col gap-4">
                {sessionIds.map((sessionId) => {
                    const summary = summaries[sessionId]
                    if (!summary) {
                        return null
                    }
                    return <SingleSessionSummary key={sessionId} sessionId={sessionId} summary={summary} />
                })}
            </div>
        </div>
    )
}

function SingleSessionSummary({
    sessionId,
    summary,
}: {
    sessionId: string
    summary: SessionSummaryEntry
}): ReactElement {
    const outcome = summary.session_outcome
    const segments = summary.segments ?? []
    const segmentOutcomes = summary.segment_outcomes ?? []
    const keyActions = summary.key_actions ?? []

    const outcomesByIndex = new Map(segmentOutcomes.map((o) => [o.segment_index, o]))
    const keyActionsByIndex = new Map(keyActions.map((ka) => [ka.segment_index, ka]))

    // Compute total session duration from segments for timeline bar positioning
    const totalDurationSec = segments.reduce((sum, s) => sum + (s.meta?.duration ?? 0), 0)
    const totalDurationMs = totalDurationSec * 1000

    return (
        <div className="flex flex-col gap-3">
            <span className="text-xs font-mono text-muted-foreground">{sessionId}</span>

            {outcome && (
                <div
                    className={cn(
                        'rounded-lg p-3 border-l-4',
                        outcome.success
                            ? 'bg-success border-success-foreground'
                            : 'bg-destructive border-destructive-foreground'
                    )}
                >
                    <div className="flex items-start gap-2">
                        {outcome.success ? (
                            <Check className="h-5 w-5 shrink-0 text-success-foreground" />
                        ) : (
                            <AlertTriangle className="h-5 w-5 shrink-0 text-destructive-foreground" />
                        )}
                        <div>
                            <span className="text-sm font-semibold">
                                {outcome.success ? 'Session successful' : 'Session abandoned'}
                            </span>
                            <div className="text-sm mt-1">{outcome.description ?? '\u2014'}</div>
                        </div>
                    </div>
                </div>
            )}

            <span className="text-sm font-semibold">Journey</span>

            {segments.map((segment, i) => {
                const segOutcome = outcomesByIndex.get(segment.index ?? -1)
                const segActions = keyActionsByIndex.get(segment.index ?? -1)
                const widthPercent = (segment.meta?.duration_percentage ?? 0) * 100

                const firstEventMs = segActions?.events?.[0]?.milliseconds_since_start
                let offsetPercent = 0
                if (firstEventMs != null && totalDurationMs > 0) {
                    const eventOffset = (firstEventMs / totalDurationMs) * 100
                    offsetPercent = eventOffset + widthPercent > 100 ? 100 - widthPercent : eventOffset
                }

                return (
                    <SegmentCard
                        key={segment.index ?? `idx-${i}`}
                        segment={segment}
                        segOutcome={segOutcome}
                        segActions={segActions}
                        offsetPercent={offsetPercent}
                        widthPercent={widthPercent}
                    />
                )
            })}

            {summary.sentiment && <SentimentSection sentiment={summary.sentiment} />}
        </div>
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
    segOutcome?: SessionSummarySegmentOutcome | undefined
    segActions?: { segment_index?: number | null; events?: KeyActionEvent[] | null } | undefined
    offsetPercent: number
    widthPercent: number
}): ReactElement {
    const [expanded, setExpanded] = useState(false)
    const issues = issueCount(segment)
    const hasEvents = segActions?.events && segActions.events.length > 0

    const borderClass =
        segOutcome?.success === false
            ? 'border-l-destructive'
            : segOutcome?.success === true
              ? 'border-l-success'
              : 'border-l-border'

    return (
        <div className="rounded-lg border bg-card overflow-hidden">
            <div
                onClick={hasEvents ? () => setExpanded(!expanded) : undefined}
                className={cn('border-l-4 px-4 py-3', borderClass, hasEvents ? 'cursor-pointer' : 'cursor-default')}
            >
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        {hasEvents && (
                            <ChevronRight
                                className={cn(
                                    'h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150',
                                    expanded && 'rotate-90'
                                )}
                            />
                        )}
                        <span className="text-sm font-semibold flex-1">
                            {segment.name ?? `Segment ${segment.index}`}
                        </span>
                        {issues > 0 && (
                            <Badge variant="destructive">
                                {issues} {issues === 1 ? 'issue' : 'issues'}
                            </Badge>
                        )}
                        {segOutcome?.success !== undefined && segOutcome?.success !== null && (
                            <Badge variant={segOutcome.success ? 'success' : 'destructive'}>
                                {segOutcome.success ? 'success' : 'failed'}
                            </Badge>
                        )}
                    </div>

                    {segOutcome?.summary && <span className="text-sm text-muted-foreground">{segOutcome.summary}</span>}

                    <div className="flex items-center gap-3">
                        <div className="flex-1">
                            <SegmentTimelineBar
                                offsetPercent={offsetPercent}
                                widthPercent={widthPercent}
                                success={segOutcome?.success}
                            />
                        </div>
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                            {formatDuration(segment.meta?.duration)} &middot;{' '}
                            {formatPercentage(segment.meta?.duration_percentage)}
                        </span>
                    </div>
                </div>
            </div>

            {expanded && hasEvents && (
                <div className={cn('border-l-4 border-t px-4 py-2', borderClass)}>
                    <div className="flex flex-col gap-0">
                        {segActions.events!.map((event, i) => (
                            <div key={i} className={cn('py-2', i < segActions.events!.length - 1 && 'border-b')}>
                                <div className="flex items-start gap-3">
                                    {event.milliseconds_since_start != null && (
                                        <span className="text-xs font-mono whitespace-nowrap text-warning-foreground">
                                            {formatTimestamp(event.milliseconds_since_start)}
                                        </span>
                                    )}
                                    <div className="flex-1">
                                        <div className="flex items-center gap-1 flex-wrap">
                                            <span className="text-xs">{event.description}</span>
                                            {event.exception && <Badge variant="destructive">{event.exception}</Badge>}
                                            {event.abandonment && <Badge variant="warning">abandonment</Badge>}
                                            {event.confusion && <Badge variant="warning">confusion</Badge>}
                                        </div>
                                        {event.current_url && (
                                            <span className="text-xs text-muted-foreground">{event.current_url}</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

function SentimentSection({ sentiment }: { sentiment: SessionSummarySentiment }): ReactElement {
    return (
        <Card>
            <CardContent>
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-3">
                        <span className="text-sm font-semibold">Sentiment</span>
                        {sentiment.outcome && (
                            <Badge
                                variant={
                                    sentiment.outcome === 'successful'
                                        ? 'success'
                                        : sentiment.outcome === 'friction'
                                          ? 'warning'
                                          : 'destructive'
                                }
                            >
                                {sentiment.outcome}
                            </Badge>
                        )}
                    </div>
                    {sentiment.frustration_score != null && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">Frustration:</span>
                            <Progress
                                value={Math.round(sentiment.frustration_score * 100)}
                                variant={
                                    sentiment.outcome === 'successful'
                                        ? 'success'
                                        : sentiment.outcome === 'friction'
                                          ? 'warning'
                                          : 'destructive'
                                }
                                className="w-25"
                            />
                            <span className="text-xs text-muted-foreground">
                                {Math.round(sentiment.frustration_score * 100)}%
                            </span>
                        </div>
                    )}
                </div>
            </CardContent>
        </Card>
    )
}
