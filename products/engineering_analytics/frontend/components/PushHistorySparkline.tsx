import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { PushRound, pushRoundColor, pushRoundVerdictLabel } from '../lib/pushRounds'

export interface PushHistorySparklineProps {
    /** Oldest first. */
    rounds: PushRound[]
    ariaLabel?: string
    /** Fewer pushes than this right-align as narrow bars instead of stretching. */
    minSlots?: number
    className?: string
}

const VIEW_HEIGHT = 100
const BASELINE_Y = 96
const TOP_PAD = 6
// A push with runs is always a visible tick, even when its wall time rounds to nothing.
const MIN_BAR_HEIGHT = 10
const BAR_INSET = 0.18

export function PushHistorySparkline({
    rounds,
    ariaLabel = 'Push CI history',
    minSlots,
    className,
}: PushHistorySparklineProps): JSX.Element | null {
    if (rounds.length === 0) {
        return null
    }
    const maxWall = Math.max(...rounds.map((round) => round.wallSeconds ?? 0), 1)
    const usableHeight = BASELINE_Y - TOP_PAD
    const slots = Math.max(rounds.length, minSlots ?? 0, 1)
    const offset = slots - rounds.length

    return (
        <svg
            className={cn('h-7 w-full overflow-visible', className)}
            viewBox={`0 0 ${slots} ${VIEW_HEIGHT}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={ariaLabel}
        >
            <line
                x1={0}
                y1={BASELINE_Y}
                x2={slots}
                y2={BASELINE_Y}
                stroke="var(--muted)"
                strokeWidth={1}
                strokeDasharray="1 2"
                vectorEffect="non-scaling-stroke"
            />
            {rounds.map((round, i) => {
                const barHeight =
                    round.wallSeconds != null
                        ? Math.max(MIN_BAR_HEIGHT, (round.wallSeconds / maxWall) * usableHeight)
                        : MIN_BAR_HEIGHT
                const label = `${round.headSha.slice(0, 7)} · ${
                    round.wallSeconds != null ? humanFriendlyDuration(round.wallSeconds) : 'no completed runs'
                } · ${pushRoundVerdictLabel(round)}`
                return (
                    <g key={round.headSha || i}>
                        <rect
                            x={offset + i + BAR_INSET}
                            y={BASELINE_Y - barHeight}
                            width={1 - BAR_INSET * 2}
                            height={barHeight}
                            fill={pushRoundColor(round)}
                            fillOpacity={round.failed ? 1 : round.pending ? 0.9 : 0.55}
                        />
                        {/* Full-height transparent hit area so hovering a short bar still shows its title. */}
                        <rect x={offset + i} y={0} width={1} height={VIEW_HEIGHT} fill="transparent">
                            <title>{label}</title>
                        </rect>
                    </g>
                )
            })}
        </svg>
    )
}
