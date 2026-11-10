import { memo, MouseEvent, FocusEvent, useEffect, useMemo, useRef, useState } from 'react'

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
const TOOLTIP_DELAY_MS = 400
const BOX_CLASS = 'block h-3 w-2 shrink-0 rounded-[2px] transition-transform duration-100 hover:scale-y-125'
const COLUMN_CLASS = 'flex h-4 w-2 shrink-0 flex-col items-center justify-end'

function runDescription(run: SignalScoutRunSummary, now: Date, costUsd: number | undefined): string {
    const parts = [scoutRunOutcomeLabel(run, now)]
    const duration = formatRunDuration(runDurationSeconds(run, now))
    if (duration) {
        parts.push(duration)
    }
    if (run.started_at) {
        parts.push(humanFriendlyDetailedTime(run.started_at))
    }
    // Only runs with recorded usage carry a cost, so every other run's tooltip omits the segment.
    if (costUsd !== undefined) {
        parts.push(formatRunCost(costUsd))
    }
    if (run.task_url) {
        parts.push('open task run')
    }
    return parts.join(' · ')
}

interface ActiveBox {
    runId: string
    left: number
    top: number
    width: number
    height: number
}

function columnOf(target: EventTarget, strip: HTMLElement): HTMLElement | null {
    const column = target instanceof Element ? target.closest<HTMLElement>('[data-run-id]') : null
    return column && strip.contains(column) ? column : null
}

function activeBoxOf(column: HTMLElement): ActiveBox {
    return {
        runId: column.dataset.runId ?? '',
        left: column.offsetLeft,
        top: column.offsetTop,
        width: column.offsetWidth,
        height: column.offsetHeight,
    }
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
export const ScoutRunBoxes = memo(function ScoutRunBoxes({
    runs,
    costs,
}: {
    runs: SignalScoutRunSummary[]
    costs?: Map<string, number>
}): JSX.Element | null {
    const visible = useMemo(() => {
        const now = new Date()
        return runs.slice(-MAX_BOXES).map((run) => ({
            run,
            outcome: deriveRunOutcome(run, now),
            description: runDescription(run, now, costs?.get(run.run_id)),
        }))
    }, [runs, costs])
    const [activeBox, setActiveBox] = useState<ActiveBox | null>(null)
    const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const pendingRunId = useRef<string | null>(null)
    const isOpen = activeBox !== null

    const clearHoverTimer = (): void => {
        if (hoverTimer.current !== null) {
            clearTimeout(hoverTimer.current)
            hoverTimer.current = null
        }
        pendingRunId.current = null
    }

    const close = (): void => {
        clearHoverTimer()
        setActiveBox(null)
    }

    useEffect(() => clearHoverTimer, [])

    useEffect(() => {
        if (!isOpen) {
            return
        }
        const dismiss = (): void => setActiveBox(null)
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                dismiss()
            }
        }
        window.addEventListener('scroll', dismiss, { capture: true, passive: true })
        document.addEventListener('keydown', onKeyDown)
        return () => {
            window.removeEventListener('scroll', dismiss, { capture: true })
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [isOpen])

    if (runs.length === 0) {
        return null
    }
    const hidden = runs.length - visible.length

    // Newest first so flex-row-reverse renders them right-to-left; the oldest
    // runs (and the +N marker) sit at the left edge and clip away first.
    const newestFirst = visible.slice().reverse()
    const activeEntry = activeBox ? visible.find(({ run }) => run.run_id === activeBox.runId) : undefined

    const onMouseOver = (event: MouseEvent<HTMLDivElement>): void => {
        const column = columnOf(event.target, event.currentTarget)
        if (!column) {
            close()
            return
        }
        const runId = column.dataset.runId
        if (runId === activeBox?.runId || runId === pendingRunId.current) {
            return
        }
        clearHoverTimer()
        if (activeBox) {
            setActiveBox(activeBoxOf(column))
            return
        }
        pendingRunId.current = runId ?? null
        hoverTimer.current = setTimeout(() => {
            pendingRunId.current = null
            hoverTimer.current = null
            setActiveBox(activeBoxOf(column))
        }, TOOLTIP_DELAY_MS)
    }

    const onFocus = (event: FocusEvent<HTMLDivElement>): void => {
        const column = columnOf(event.target, event.currentTarget)
        if (column) {
            clearHoverTimer()
            setActiveBox(activeBoxOf(column))
        }
    }

    return (
        <div
            className="relative flex flex-row-reverse items-center gap-1 min-w-0 overflow-hidden"
            onMouseOver={onMouseOver}
            onMouseLeave={close}
            onFocus={onFocus}
            onBlur={close}
            onClick={close}
        >
            {newestFirst.map(({ run, outcome, description }) => {
                const boxClass = `${BOX_CLASS} ${OUTCOME_BOX_CLASS[outcome]}`
                // The label is an attribute, not an `sr-only` child: the roster renders a strip per
                // scout, so one more node per box adds thousands of nodes to a large fleet.
                const column = <span className={boxClass} role="img" aria-label={`Run ${description}`} />
                // The whole column links, not only the box, because the tooltip spans the column
                // and offers to open the task run.
                return run.task_url ? (
                    <Link key={run.run_id} to={run.task_url} className={COLUMN_CLASS} data-run-id={run.run_id}>
                        {column}
                    </Link>
                ) : (
                    <span key={run.run_id} className={COLUMN_CLASS} data-run-id={run.run_id}>
                        {column}
                    </span>
                )
            })}
            {hidden > 0 ? <span className="shrink-0 text-[10px] text-muted">+{hidden}</span> : null}
            {activeBox && activeEntry ? (
                <Tooltip visible title={activeEntry.description}>
                    <span
                        aria-hidden
                        className="pointer-events-none absolute"
                        style={{
                            left: activeBox.left,
                            top: activeBox.top,
                            width: activeBox.width,
                            height: activeBox.height,
                        }}
                    />
                </Tooltip>
            ) : null}
        </div>
    )
})
