import { useMemo } from 'react'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { SignalScoutRunSummary } from '../../../types'
import {
    deriveRunOutcome,
    formatRunCost,
    formatRunDuration,
    runDurationSeconds,
    ScoutRunOutcome,
    scoutRunOutcomeLabel,
} from '../../../utils/scoutRunsWindow'

// Quiet is the common, healthy baseline so it recedes to muted; saturated color
// only means something happened – blue emission payoff, red/amber trouble. Blue
// (not the orange brand primary) keeps this in step with the PostHog Desktop app.
const OUTCOME_BOX_CLASS: Record<ScoutRunOutcome, string> = {
    emitted: 'bg-brand-blue',
    // A report-channel run produced output too — same payoff blue as an emitting run.
    reported: 'bg-brand-blue',
    quiet: 'bg-border-bold',
    error: 'bg-danger',
    timed_out: 'bg-warning',
    running: 'bg-brand-blue animate-pulse',
    stuck: 'bg-danger animate-pulse',
    queued: 'border border-border-bold bg-transparent',
    unknown: 'bg-border',
}

const MAX_BOXES = 24
const BOX_CLASS = 'block h-3 w-2 shrink-0 rounded-[2px] transition-transform duration-100 hover:scale-y-125'
// A box column always keeps the marker's height, priced or not, so the strip does not jump a few
// pixels when the costs land a moment after the runs.
const COLUMN_CLASS = 'flex h-4 w-2 shrink-0 flex-col items-center justify-end gap-px'
const MARKER_CLASS = 'block h-[3px] w-2 rounded-[1px] bg-brand-yellow'

function runTooltip(run: SignalScoutRunSummary, now: Date, costUsd: number | undefined, expensive: boolean): string {
    const parts = [scoutRunOutcomeLabel(run, now)]
    const duration = formatRunDuration(runDurationSeconds(run, now))
    if (duration) {
        parts.push(duration)
    }
    if (run.started_at) {
        parts.push(humanFriendlyDetailedTime(run.started_at))
    }
    // Only staff are given costs, and only for runs with model spend attributed to them, so the
    // rest of the tooltip reads the same as before.
    if (costUsd !== undefined) {
        parts.push(formatRunCost(costUsd))
    }
    // The marker is a colored bar, so say the same thing in words for anyone reading the tooltip
    // or the screen-reader label.
    if (expensive) {
        parts.push('top 10% of runs by cost')
    }
    return parts.join(' · ')
}

/**
 * One small box per run in the visible window, oldest on the left. Each box
 * links out to cloud's Tasks UI via the run's relative `task_url`; runs without
 * a task link are tooltip-only.
 *
 * Laid out with `flex-row-reverse` (newest first in the DOM) so that when the
 * row is too narrow for every box the container clips the oldest runs off the
 * left edge, keeping the most recent activity always visible.
 *
 * The strip therefore hangs off the RIGHT of whatever contains it, and it should stay that way:
 * scouts hold different numbers of runs, so right-anchoring puts every row's newest run on one
 * vertical line. Left-aligning instead scatters the newest run across the column by run count,
 * which is the one box a reader is scanning for.
 */
export function ScoutRunBoxes({
    runs,
    costs,
    costThreshold,
}: {
    runs: SignalScoutRunSummary[]
    costs?: Map<string, number>
    costThreshold?: number | null
}): JSX.Element | null {
    const visible = useMemo(() => {
        const now = new Date()
        return runs.slice(-MAX_BOXES).map((run) => {
            const costUsd = costs?.get(run.run_id)
            const expensive = costUsd !== undefined && costThreshold != null && costUsd >= costThreshold
            return {
                run,
                outcome: deriveRunOutcome(run, now),
                expensive,
                tooltip: runTooltip(run, now, costUsd, expensive),
            }
        })
    }, [runs, costs, costThreshold])

    if (runs.length === 0) {
        return null
    }
    const hidden = runs.length - visible.length

    // Newest first so flex-row-reverse renders them right-to-left; the oldest
    // runs (and the +N marker) sit at the left edge and clip away first.
    const newestFirst = visible.slice().reverse()

    return (
        <div className="flex flex-row-reverse items-center gap-1 min-w-0 overflow-hidden">
            {newestFirst.map(({ run, outcome, expensive, tooltip }) => {
                const boxClass = `${BOX_CLASS} ${OUTCOME_BOX_CLASS[outcome]}`
                const boxTooltip = run.task_url ? `${tooltip} · open task run` : tooltip
                const label = <span className="sr-only">Run {boxTooltip}</span>
                const column = (
                    <>
                        {expensive ? <span className={MARKER_CLASS} /> : null}
                        <span className={boxClass}>{label}</span>
                    </>
                )
                // The whole column links, not only the box, because the tooltip spans the column
                // and offers to open the task run. A marker left outside the link would not
                // navigate there: the roster card holds no handler above the box, and the roster
                // table's row handler pushes the scout page for every click that is not inside an
                // `a` or `button`.
                return (
                    <Tooltip key={run.run_id} title={boxTooltip}>
                        {run.task_url ? (
                            <Link to={run.task_url} className={COLUMN_CLASS}>
                                {column}
                            </Link>
                        ) : (
                            <span className={COLUMN_CLASS}>{column}</span>
                        )}
                    </Tooltip>
                )
            })}
            {hidden > 0 ? <span className="shrink-0 text-[10px] text-muted">+{hidden}</span> : null}
        </div>
    )
}
