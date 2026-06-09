import { JSX } from 'react'

import { DiffStatsChip } from './DiffStatsChip'
import { formatDuration, GeneratingIndicator } from './GeneratingIndicator'
import { IconBrain, ICONS } from './primitives/icons'

const IconPause = ICONS.Pause

interface DiffStats {
    additions: number
    deletions: number
}

interface SessionFooterProps {
    /** Aggregated +N/-M line counts for the turn, rendered as a static chip. */
    diffStats?: DiffStats | null
    /** Whether a prompt is still in flight. `null` for replayed/cloud transcripts. */
    isPromptPending: boolean | null
    /** Timestamp (ms) when the pending prompt started; drives the live timer. */
    promptStartedAt?: number | null
    /** Duration (ms) of the last completed turn, sourced from `LastTurnInfo`. */
    lastGenerationDuration: number | null
    /** Stop reason of the last completed turn, sourced from `LastTurnInfo`. */
    lastStopReason?: string
    /** Number of messages queued behind the current turn. */
    queuedCount?: number
    /** Whether the agent is paused awaiting a permission decision. */
    hasPendingPermission?: boolean
    /** Accumulated paused time (ms) subtracted from the live timer. */
    pausedDurationMs?: number
    /** Whether the agent is compacting context (suppresses the generating state). */
    isCompacting?: boolean
}

/**
 * Read-only summary row shown beneath a conversation turn.
 *
 * Ported from PostHog Code's `SessionFooter`. The Electron version also rendered
 * a live `ContextUsageIndicator`; that affordance is dropped here because the
 * transcript is read-only and no live usage stream is available. Pending states
 * (generating / awaiting permission) are still rendered so replayed-while-live
 * transcripts read correctly, but no input or controls are exposed.
 */
export function SessionFooter({
    diffStats,
    isPromptPending,
    promptStartedAt,
    lastGenerationDuration,
    lastStopReason,
    queuedCount = 0,
    hasPendingPermission = false,
    pausedDurationMs,
    isCompacting = false,
}: SessionFooterProps): JSX.Element {
    const rightSide = (
        <div className="flex items-center gap-3 ml-auto shrink-0">
            {diffStats && <DiffStatsChip additions={diffStats.additions} deletions={diffStats.deletions} />}
        </div>
    )

    if (isPromptPending && !isCompacting) {
        if (hasPendingPermission) {
            return (
                <div className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
                    <div className="flex items-center justify-between gap-2">
                        <div
                            className="flex items-center gap-2 min-w-0 select-none text-muted"
                            style={{ WebkitUserSelect: 'none' }}
                        >
                            <IconPause className="shrink-0" style={{ fontSize: 14 }} />
                            <span className="truncate text-[13px] text-muted">Awaiting permission...</span>
                        </div>
                        {rightSide}
                    </div>
                </div>
            )
        }

        return (
            <div className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                        <GeneratingIndicator startedAt={promptStartedAt} pausedDurationMs={pausedDurationMs} />
                        {queuedCount > 0 && (
                            <span className="truncate text-[13px] text-muted">({queuedCount} queued)</span>
                        )}
                    </div>
                    {rightSide}
                </div>
            </div>
        )
    }

    const wasCancelled = lastStopReason === 'cancelled' || lastStopReason === 'refusal'

    const showDuration = lastGenerationDuration !== null && lastGenerationDuration > 0 && !wasCancelled

    return (
        <div className="pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
            <div className="flex items-center justify-between gap-2">
                {showDuration && (
                    <div className="flex items-center gap-2 min-w-0 select-none text-muted">
                        <IconBrain className="shrink-0" style={{ fontSize: 12 }} />
                        <span className="truncate text-[13px] text-muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
                            Generated in {formatDuration(lastGenerationDuration)}
                        </span>
                    </div>
                )}
                {rightSide}
            </div>
        </div>
    )
}
